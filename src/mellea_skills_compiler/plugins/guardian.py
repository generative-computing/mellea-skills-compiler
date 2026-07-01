"""Granite Guardian audit hook for Mellea pipelines.

Intercepts generation_post_call, sends the LLM output to Granite Guardian
and records the safety verdict in
user_metadata for downstream audit hooks.

Two modes:
  - AUDIT (default): observe-only, verdicts are logged but generation proceeds.
  - ENFORCE: SEQUENTIAL mode, returns block() when any risk is flagged,
    raising PluginViolationError to halt the pipeline.

Usage (audit mode — observe only):
    from guardian_hook import GuardianAuditPlugin
    plugin = GuardianAuditPlugin(risks=["harm", "jailbreak"])
    register(plugin)

Usage (enforce mode — blocks on risk):
    from guardian_hook import GuardianAuditPlugin
    plugin = GuardianAuditPlugin(risks=["harm", "jailbreak"], enforce=True)
    register(plugin)
"""

from __future__ import annotations

import json
import urllib.error
from copy import deepcopy
from typing import Any, List, Optional

from mellea.core.requirement import Requirement
from mellea.plugins import HookType, Plugin, PluginMode, hook
from mellea.plugins.registry import block
from mellea.stdlib.components.genstub import SyncGenerativeStub
from mellea.stdlib.components.instruction import Instruction
from rich.console import Console

from mellea_skills_compiler.enums import (
    GuardianMode,
    GuardianScore,
    InferenceEngineType,
)
from mellea_skills_compiler.inference import InferenceService
from mellea_skills_compiler.models import GuardianVerdict, NexusRisk, PolicyManifest
from mellea_skills_compiler.plugins import BasePlugin
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console()
GUARDIAN_RETRY_ATTEMPTS = 2


def _parse_guardian_score(text: str) -> str:
    """Extract Yes/No from Guardian <score> tags."""
    s = text.lower()
    if "<score>" in s and "</score>" in s:
        score = s.split("<score>")[1].split("</score>")[0].strip()
        if score == "yes":
            return GuardianScore.YES
        if score == "no":
            return GuardianScore.NO
    return GuardianScore.FAILED


def _call_guardian(
    risks: List[NexusRisk],
    input_text: str,
    assistant_text: Optional[str] = None,
    guardian_model: Optional[str] = None,
    inference_engine: Optional[str] = None,
) -> List[GuardianVerdict]:
    """Synchronous call to Guardian.

    Guardian expects a chat with the user turn (+ optional assistant turn)
    and a system prompt specifying the risk to evaluate.

    The ``risk`` parameter is the Guardian system prompt content:
      - For native risks (from Nexus ``tag`` field): a bare risk name like
        ``"harm"``, ``"social_bias"``, ``"jailbreak"`` — Guardian uses its
        calibrated assessment path for these.
      - For custom criteria (no Nexus ``tag``): description text
        sent as free-form custom criteria.

    This distinction is set upstream in ``policy.py`` via the
    two-tier calling convention (see NexusRisk.is_native).

    When assistant_text is None, this is a pre-generation check on the
    input prompt only (the GAF-Guard pattern). When assistant_text is
    provided, this is a post-generation check on the output.

    Guardian response format: ``<score>yes</score>`` (risk detected) or
    ``<score>no</score>`` (safe).
    """

    # Extract risk names and their prompts
    risk_names = [r.name for r in risks]
    guardian_prompts = [r.guardian_prompt for r in risks]

    # Create guardian message prompts
    all_messages = []
    for guardian_prompt in guardian_prompts:
        messages = [{"role": "system", "content": guardian_prompt}]
        if input_text:
            messages.append({"role": "user", "content": input_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})
        all_messages.append(messages)

    try:
        # Load inference model
        guardian_model = InferenceService(inference_engine).guardian(
            guardian_model, parameters={"temperature": 0}
        )

        # Batch inferencing guardian risks
        raw_predictions = [
            raw_prediction.prediction
            for raw_prediction in guardian_model.chat(all_messages, verbose=False)
        ]

    except Exception as e:
        LOGGER.warning("Guardian call failed for risks=%s: %s", risk_names, e)
        return [
            GuardianVerdict(
                risk=risk.name,
                label=GuardianScore.ERROR,
                raw_output="",
            )
            for risk in risks
        ]

    # Create Guardian Verdict
    verdicts = []
    for risk_name, messages, raw_prediction in zip(
        risk_names, all_messages, raw_predictions
    ):
        label = _parse_guardian_score(raw_prediction)

        # retry failed guardian call
        if label == GuardianScore.FAILED:
            attempt = 1
            while attempt <= GUARDIAN_RETRY_ATTEMPTS:
                LOGGER.warning(
                    f"Retrying failed guardian assessment - {risk_name}...attempt: {attempt}"
                )
                console.print(
                    f"[white]  risk={messages[0]['content']}\n  label={label}\n  preview={assistant_text.replace("\n", " ")[0:90] if assistant_text else input_text.replace("\n", " ")[0:90]}[/]"
                )

                try:
                    raw_prediction = guardian_model.chat([messages], verbose=False)[
                        0
                    ].prediction
                    label = _parse_guardian_score(raw_prediction)
                except Exception as e:
                    LOGGER.warning("Guardian call failed for risk=%s: %s", risk_name, e)
                    label = GuardianScore.ERROR
                    raw_prediction = ""

                if label not in [GuardianScore.FAILED, GuardianScore.ERROR]:
                    break

                attempt += 1

        verdicts.append(
            GuardianVerdict(risk=risk_name, label=label, raw_output=raw_prediction)
        )

    return verdicts


def _run_guardian_post_checks(
    payload: Any, risks: List[NexusRisk], guardian_model: str, inference_engine: str
) -> List[GuardianVerdict]:
    """Shared logic: run Guardian checks and return (verdicts, flagged_labels)."""
    model_output = payload.model_output
    if model_output is None:
        return []

    if isinstance(model_output._action, Requirement):
        # No need to assess Requirement output here as the final post generation output
        # is more suitable place for monitoring.
        return []

    assistant_text = getattr(model_output, "value", None) or ""
    if not assistant_text:
        return []

    # Reconstruct the user prompt from the payload
    prompt = payload.prompt
    if isinstance(prompt, list):
        input_text = ""
        for msg in reversed(list(prompt)):
            if isinstance(msg, dict) and msg.get("role") == "user":
                input_text = msg.get("content", "")
                break
    else:
        input_text = str(prompt) if prompt else ""

    verdicts: List[GuardianVerdict] = _call_guardian(
        risks,
        input_text,
        assistant_text,
        guardian_model,
        inference_engine,
    )
    for verdict in verdicts:
        console.print(
            f"Plugin-[green]\\[guardian-post][/]\n  [white]risk={verdict.risk}\n  label={verdict.label}\n  output_preview={assistant_text.replace("\n", " ")[0:90]}[/]"
        )
    return verdicts


def _run_guardian_pre_checks(
    payload: Any, risks: List[NexusRisk], guardian_model: str, inference_engine: str
) -> List[GuardianVerdict]:
    """Pre-generation check: assess the input prompt before LLM generation.

    Follows the GAF-Guard pattern — system + user only, no assistant turn.
    """

    # Extract action from the CBlock or Component/Instruction
    action = payload.action
    if action is None:
        return []

    # Get input text from the action component
    input_text = action.format_for_llm().args
    if isinstance(action, SyncGenerativeStub):
        input_text = str(input_text["arguments"])
    elif isinstance(action, Instruction):
        input_text_clean = {}
        for key, value in input_text.items():
            if value:
                input_text_clean.update({key: value})
        input_text = json.dumps(input_text_clean, default=lambda x: str(x), indent=2)
    elif isinstance(action, Requirement):
        # No need to assess Requirement here as the final post generation output
        # is more suitable place for monitoring
        return []
    else:
        # Fallback method to extract input text
        input_text = (
            getattr(action, "description", None)
            or getattr(action, "_description", None)
            or getattr(action, "_arguments", None)
            or action
        )
        input_text = getattr(input_text, "value", None) or str(input_text)

    if not input_text:
        return []

    assistant_text = None
    verdicts: List[GuardianVerdict] = _call_guardian(
        risks,
        input_text,
        assistant_text,
        guardian_model,
        inference_engine,
    )
    for verdict in verdicts:
        console.print(
            f"Plugin-[blue]\\[guardian-pre][/]\n  [white]risk={verdict.risk}\n  label={verdict.label}\n  input_preview={input_text.replace("\n", " ")[0:90]}[/]"
        )
    return verdicts


class GuardianPluginFactory:

    def create(guardian_mode: GuardianMode, *args, **kwargs):
        guardian_plugin_class = (
            GuardianEnforcePlugin
            if guardian_mode == GuardianMode.ENFORCE
            else GuardianAuditPlugin
        )
        return guardian_plugin_class(*args, **kwargs)


class GuardianPlugin(BasePlugin):
    """Shared state and factory methods for Guardian plugins."""

    def __init__(
        self,
        manifest: PolicyManifest,
        guardian_model: Optional[str] = None,
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        """Create plugin from a Nexus PolicyManifest.

        Args:
            manifest: A PolicyManifest with guardian_risks and risk_names.
            enforce: If True, returns a GuardianEnforcePlugin (SEQUENTIAL mode)
                that blocks generation when risks are detected.
            guardian_model: The guardian model
            inference_engine: The inference engine, defaults to Ollama
        """
        self.risks = manifest.risks
        self.taxonomy = manifest.taxonomy
        self.all_verdicts: List[GuardianVerdict] = []
        self.guardian_model = guardian_model
        self.inference_engine = inference_engine

    def register(self) -> None:
        native = [r for r in self.risks if r.is_native]
        custom = [r for r in self.risks if not r.is_native]
        LOGGER.info(
            f"Guardian plugin registered [{self._PLUGIN_MODE} mode]: {len(self.risks)} risks — {len(native)} native, {len(custom)} custom criteria"
        )
        super().register()

    def summary(self) -> dict:
        return {
            "all_verdicts": self.all_verdicts,
            "flagged_verdicts": [
                v for v in self.all_verdicts if v.label == GuardianScore.YES
            ],
            "passed_verdicts": [
                v for v in self.all_verdicts if v.label == GuardianScore.NO
            ],
            "failed_verdicts": [
                v
                for v in self.all_verdicts
                if v.label in [GuardianScore.FAILED, GuardianScore.ERROR]
            ],
        }


class GuardianAuditPlugin(
    GuardianPlugin, Plugin, name="granite-guardian-audit", priority=40
):
    """Observe-only Guardian hook (AUDIT mode).

    Scans every LLM output against Granite Guardian risk checks.
    Verdicts are logged and stored but generation is never blocked.

    For enforcement mode, use ``GuardianAuditPlugin.from_manifest(manifest, enforce=True)``
    which returns a ``GuardianEnforcePlugin`` instead.
    """

    _PLUGIN_MODE = GuardianMode.AUDIT

    def __init__(
        self,
        manifest: PolicyManifest,
        guardian_model: Optional[str] = None,
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        super().__init__(manifest, guardian_model, inference_engine)

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.AUDIT)
    async def check_input(self, payload: Any, ctx: Any) -> None:
        """Pre-generation: assess input prompt for risks (observe-only)."""
        verdicts = _run_guardian_pre_checks(
            payload, self.risks, self.guardian_model, self.inference_engine
        )
        self.all_verdicts.extend(verdicts)

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.AUDIT)
    async def check_output(self, payload: Any, ctx: Any) -> None:
        """Post-generation: assess LLM output for risks (observe-only)."""
        verdicts = _run_guardian_post_checks(
            payload, self.risks, self.guardian_model, self.inference_engine
        )
        self.all_verdicts.extend(verdicts)

    @hook(HookType.TOOL_PRE_INVOKE, mode=PluginMode.AUDIT)
    async def check_tool_input(self, payload: Any, ctx: Any) -> None:
        """Pre-tool: log the tool call about to be executed (observe-only).

        For Pattern 3 (LLM-directed tool calls via ModelOption.TOOLS).
        Pattern 2 tool calls don't go through Mellea hooks — they use
        code-level governance instead.
        """
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        args = getattr(tool_call, "args", {})
        LOGGER.info(f"[guardian-pre-tool] {tool_name}(args={str(args)[:100]})")

    @hook(HookType.TOOL_POST_INVOKE, mode=PluginMode.AUDIT)
    async def check_tool_output(self, payload: Any, ctx: Any) -> None:
        """Post-tool: scan tool output for risks (observe-only).

        Sends the tool output through Guardian risk checks to detect
        harmful, biased, or sensitive content returned by external tools.
        """
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        tool_output = str(payload.tool_output or "")
        latency = payload.execution_time_ms

        LOGGER.info(
            f"[guardian-post-tool] {tool_name} — {'error' if not payload.success else str(len(tool_output)) + " bytes"}, {latency}ms"
        )

        if not (not tool_output or not payload.success):

            tool_risks = []
            for risk in self.risks:
                tool_risk = deepcopy(risk)
                tool_risk.name = f"tool:{tool_risk.name}"
                tool_risks.append(tool_risk)

            # Run Guardian checks on the tool output (treat as assistant text)
            verdicts: list[GuardianVerdict] = _call_guardian(
                tool_risks,
                user_text=f"Tool {tool_name} was called",
                assistant_text=tool_output[:2000],
                guardian_model=self.guardian_model,
                inference_engine=self.inference_engine,
            )
            self.all_verdicts.extend(verdicts)

            flagged = [v.risk for v in verdicts if v.label == GuardianScore.YES]
            if flagged:
                risk_list = ", ".join(flagged)
                console.print()
                console.print(
                    f"[yellow]Plugin-\\[guardian-post-tool][/]\n  RISK IN {tool_name} output: {risk_list}"
                )
                console.print()


class GuardianEnforcePlugin(
    GuardianPlugin, Plugin, name="granite-guardian-enforce", priority=40
):
    """Enforcement Guardian hook (SEQUENTIAL mode).

    Scans every LLM output against Granite Guardian risk checks.
    If any risk is flagged, returns block() to halt the pipeline
    with a PluginViolationError.
    """

    _PLUGIN_MODE = GuardianMode.ENFORCE

    def __init__(
        self,
        manifest: PolicyManifest,
        guardian_model: Optional[str] = None,
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        super().__init__(manifest, guardian_model, inference_engine)

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_input(self, payload: Any, ctx: Any) -> Any:
        """Pre-generation: block if input prompt has risks."""
        verdicts: List[GuardianVerdict] = _run_guardian_pre_checks(
            payload, self.risks, self.guardian_model, self.inference_engine
        )
        self.all_verdicts.extend(verdicts)

        flagged = [v.risk for v in verdicts if v.label == GuardianScore.YES]
        failed = [
            v.risk
            for v in verdicts
            if v.label in [GuardianScore.ERROR, GuardianScore.FAILED]
        ]
        if failed:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-pre-enforce][/]\n  BLOCKING INPUT — risks assessment failed for {failed}"
            )
            console.print()
            return block(
                reason=f"Guardian input risks assessment failed for {failed}",
                code="guardian_input_risk_failure",
                details={"failed_risks": failed, "stage": "pre_generation"},
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-pre-enforce][/]\n  BLOCKING INPUT — risks flagged for {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected input risks for {flagged}",
                code="guardian_input_risk_detected",
                details={"flagged_risks": flagged, "stage": "pre_generation"},
            )
        return None

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_output(self, payload: Any, ctx: Any) -> Any:
        """Post-generation: block if LLM output has risks."""
        verdicts = _run_guardian_post_checks(
            payload, self.risks, self.guardian_model, self.inference_engine
        )
        self.all_verdicts.extend(verdicts)

        flagged = [v.risk for v in verdicts if v.label == GuardianScore.YES]
        failed = [
            v.risk
            for v in verdicts
            if v.label in [GuardianScore.ERROR, GuardianScore.FAILED]
        ]
        if failed:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-pre-enforce][/]\n  BLOCKING OUTPUT — risks assessment failed for {failed}"
            )
            console.print()
            return block(
                reason=f"Guardian output risks assessment failed for {failed}",
                code="guardian_output_risk_failure",
                details={"failed_risks": failed, "stage": "post_generation"},
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-post-enforce][/]\n  BLOCKING OUTPUT — risks flagged for {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected output risks for {flagged}",
                code="guardian_output_risk_detected",
                details={"flagged_risks": flagged, "stage": "post_generation"},
            )
        return None

    @hook(HookType.TOOL_PRE_INVOKE, mode=PluginMode.SEQUENTIAL)
    async def enforce_tool_input(self, payload: Any, ctx: Any) -> Any:
        """Pre-tool: log the tool call (enforcement reserved for post-invoke)."""
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        args = getattr(tool_call, "args", {})

        tool_risks = []
        for risk in self.risks:
            tool_risk = deepcopy(risk)
            tool_risk.name = f"tool:{tool_risk.name}"
            tool_risks.append(tool_risk)

        # Run Guardian checks on tool input
        verdicts: list[GuardianVerdict] = _call_guardian(
            tool_risks,
            input_text=f"Tool {tool_name} was called with arguments: {json.dumps(args, indent=2)}",
            guardian_model=self.guardian_model,
            inference_engine=self.inference_engine,
        )
        self.all_verdicts.extend(verdicts)

        flagged = [v.risk for v in verdicts if v.label == GuardianScore.YES]
        failed = [
            v.risk
            for v in verdicts
            if v.label in [GuardianScore.ERROR, GuardianScore.FAILED]
        ]
        if failed:
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL INPUT — risks failed in {tool_name}: {failed}"
            )
            console.print()
            return block(
                reason=f"Guardian tool input risks assessment failed for {failed}",
                code="guardian_tool_output_risk_failure",
                details={
                    "failed_risks": failed,
                    "tool": tool_name,
                    "stage": "pre_tool",
                },
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL INPUT — risks in {tool_name}: {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected risks in {tool_name}: {flagged}",
                code="guardian_tool_input_risk_detected",
                details={
                    "flagged_risks": flagged,
                    "tool": tool_name,
                    "stage": "pre_tool",
                },
            )
        return None

    @hook(HookType.TOOL_POST_INVOKE, mode=PluginMode.SEQUENTIAL)
    async def enforce_tool_output(self, payload: Any, ctx: Any) -> Any:
        """Post-tool: block if tool output contains risks."""
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        tool_output = str(payload.tool_output or "")

        if not tool_output or not payload.success:
            return None

        tool_risks = []
        for risk in self.risks:
            tool_risk = deepcopy(risk)
            tool_risk.name = f"tool:{tool_risk.name}"
            tool_risks.append(tool_risk)

        # Run Guardian checks on tool output
        verdicts: list[GuardianVerdict] = _call_guardian(
            tool_risks,
            input_text=f"Tool {tool_name} was called",
            assistant_text=tool_output[:2000],
            guardian_model=self.guardian_model,
            inference_engine=self.inference_engine,
        )
        self.all_verdicts.extend(verdicts)

        flagged = [v.risk for v in verdicts if v.label == GuardianScore.YES]
        failed = [
            v.risk
            for v in verdicts
            if v.label in [GuardianScore.ERROR, GuardianScore.FAILED]
        ]
        if failed:
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL OUTPUT — risks failed in {tool_name}: {failed}"
            )
            console.print()
            return block(
                reason=f"Guardian tool output risks assessment failed for {failed}",
                code="guardian_tool_output_risk_failure",
                details={
                    "failed_risks": failed,
                    "tool": tool_name,
                    "stage": "post_tool",
                },
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL OUTPUT — risks in {tool_name}: {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected risks in {tool_name}: {flagged}",
                code="guardian_tool_output_risk_detected",
                details={
                    "flagged_risks": flagged,
                    "tool": tool_name,
                    "stage": "post_tool",
                },
            )
        return None
