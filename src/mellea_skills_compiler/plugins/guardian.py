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

import asyncio
import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from mellea.core.requirement import Requirement
from mellea.plugins import HookType, Plugin, PluginMode, hook
from mellea.plugins.registry import block
from mellea.stdlib.components.genstub import SyncGenerativeStub
from mellea.stdlib.components.instruction import Instruction
from rich.console import Console

from mellea_skills_compiler.enums import (
    GuardianMode,
    GuardianScore,
    HookStage,
    InferenceEngineType,
)
from mellea_skills_compiler.models import GuardianVerdict, NexusRisk
from mellea_skills_compiler.plugins import BasePlugin
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console()
GUARDIAN_RETRY_ATTEMPTS = 2
GUARDIAN_MAX_CONCURRENCY = 4
GUARDIAN_CACHE_MAXSIZE = 512

_GUARDIAN_SEMAPHORE = threading.Semaphore(GUARDIAN_MAX_CONCURRENCY)
_VERDICT_CACHE: OrderedDict[tuple, GuardianVerdict] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _blocking_chat(inference_engine, messages_batch):
    with _GUARDIAN_SEMAPHORE:
        return inference_engine.chat(messages_batch, verbose=False)


def _cache_key(risk_name: str, judged_text: str, stage: HookStage) -> tuple:
    digest = hashlib.sha256(judged_text.encode("utf-8")).hexdigest()
    return (risk_name, digest, stage)


def _cache_get(risk_name: str, judged_text: str, stage: HookStage) -> Optional[GuardianVerdict]:
    key = _cache_key(risk_name, judged_text, stage)
    with _CACHE_LOCK:
        return _VERDICT_CACHE.get(key)


def _cache_set(risk_name: str, judged_text: str, stage: HookStage, verdict: GuardianVerdict) -> None:
    key = _cache_key(risk_name, judged_text, stage)
    with _CACHE_LOCK:
        if key in _VERDICT_CACHE:
            _VERDICT_CACHE.move_to_end(key)
        else:
            if len(_VERDICT_CACHE) >= GUARDIAN_CACHE_MAXSIZE:
                _VERDICT_CACHE.popitem(last=False)
            _VERDICT_CACHE[key] = verdict


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


async def _retry_one(risk_name: str, messages: List, inference_engine, hook_stage: HookStage) -> GuardianVerdict:
    """Retry a single failed verdict concurrently."""
    preview_source = messages[-1]["content"] if messages[-1]["role"] == "assistant" else messages[-1]["content"] if messages[-1]["role"] == "user" else ""
    preview = preview_source.replace("\n", " ")[0:90]
    console.print(
        f'[white]  risk={messages[0]["content"]}\n  preview={preview}[/]'
    )

    try:
        raw_prediction = (await asyncio.to_thread(_blocking_chat, inference_engine, [messages]))[0].prediction
        label = _parse_guardian_score(raw_prediction)
    except Exception as e:
        LOGGER.warning("Guardian call failed for risk=%s: %s", risk_name, e)
        label = GuardianScore.ERROR
        raw_prediction = ""

    return GuardianVerdict(
        risk=risk_name,
        label=label,
        raw_output=raw_prediction,
        hook_stage=hook_stage,
    )


async def _call_guardian(
    hook_stage: HookStage,
    risks: List[NexusRisk],
    input_text: str,
    inference_engine,
    assistant_text: Optional[str] = None,
    name_prefix: str = "",
) -> List[GuardianVerdict]:
    """Async call to Guardian with caching and concurrent retries.

    Guardian expects a chat with the user turn (+ optional assistant turn)
    and a system prompt specifying the risk to evaluate.

    The ``risk`` parameter is the Guardian system prompt content:
      - For native risks (from Nexus ``tag`` field): a risk name like
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

    The name_prefix is prepended to verdict.risk for tool-namespacing (e.g. "tool:").
    Cache keys use the risk.name so tool-prefixed and unprefixed verdicts
    for the same text are deduplicated.
    """

    # Construct judged text for caching
    judged_text = input_text + "\x00" + (assistant_text or "")

    # Check cache and separate cache hits from misses
    cached_verdicts = {}
    risks_to_query = []
    messages_to_query = []

    for risk in risks:
        cached = _cache_get(risk.name, judged_text, hook_stage)
        if cached:
            cached_verdicts[risk.name] = cached
        else:
            risks_to_query.append(risk)
            messages = [{"role": "system", "content": risk.guardian_prompt}]
            if input_text:
                messages.append({"role": "user", "content": input_text})
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})
            messages_to_query.append(messages)

    # Batch query for cache misses
    verdicts_by_name = dict(cached_verdicts)
    if risks_to_query:
        try:
            raw_predictions = [
                raw_prediction.prediction
                for raw_prediction in await asyncio.to_thread(_blocking_chat, inference_engine, messages_to_query)
            ]
        except Exception as e:
            LOGGER.warning("Guardian call failed for risks=%s: %s", [r.name for r in risks_to_query], e)
            for risk in risks_to_query:
                verdict = GuardianVerdict(
                    risk=risk.name,
                    label=GuardianScore.ERROR,
                    raw_output="",
                    hook_stage=hook_stage,
                )
                verdicts_by_name[risk.name] = verdict
            raw_predictions = [GuardianScore.ERROR] * len(risks_to_query)

        # Parse predictions and collect failures for retry
        failed_indices = []
        for idx, (risk, messages, raw_prediction) in enumerate(zip(risks_to_query, messages_to_query, raw_predictions)):
            label = _parse_guardian_score(raw_prediction)

            if label == GuardianScore.FAILED:
                failed_indices.append(idx)
            else:
                verdict = GuardianVerdict(
                    risk=risk.name,
                    label=label,
                    raw_output=raw_prediction,
                    hook_stage=hook_stage,
                )
                verdicts_by_name[risk.name] = verdict
                if label in [GuardianScore.YES, GuardianScore.NO]:
                    _cache_set(risk.name, judged_text, hook_stage, verdict)

        # Concurrent retries for failed predictions
        if failed_indices:
            retry_tasks = [
                _retry_one(risks_to_query[idx].name, messages_to_query[idx], inference_engine, hook_stage)
                for idx in failed_indices
            ]
            latest_by_idx = dict(zip(failed_indices, await asyncio.gather(*retry_tasks)))

            for attempt in range(GUARDIAN_RETRY_ATTEMPTS - 1):
                still_failed = [idx for idx, v in latest_by_idx.items() if v.label == GuardianScore.FAILED]
                if not still_failed:
                    break
                retry_tasks = []
                for idx in still_failed:
                    LOGGER.warning(f"Retrying failed guardian assessment - {risks_to_query[idx].name}...attempt: {attempt + 2}")
                    retry_tasks.append(_retry_one(risks_to_query[idx].name, messages_to_query[idx], inference_engine, hook_stage))
                for idx, v in zip(still_failed, await asyncio.gather(*retry_tasks)):
                    latest_by_idx[idx] = v

            for verdict in latest_by_idx.values():
                verdicts_by_name[verdict.risk] = verdict
                if verdict.label in [GuardianScore.YES, GuardianScore.NO]:
                    _cache_set(verdict.risk, judged_text, hook_stage, verdict)

    # Apply name_prefix and return in original risk order
    return [
        GuardianVerdict(
            risk=f"{name_prefix}{verdicts_by_name[r.name].risk}",
            label=verdicts_by_name[r.name].label,
            raw_output=verdicts_by_name[r.name].raw_output,
            hook_stage=verdicts_by_name[r.name].hook_stage,
        )
        for r in risks
    ]


async def _run_guardian_post_checks(
    payload: Any, risks: List[NexusRisk], inference_engine: str
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

    verdicts: List[GuardianVerdict] = await _call_guardian(
        HookStage.POST, risks, input_text, inference_engine, assistant_text
    )
    for verdict in verdicts:
        output_preview = assistant_text.replace("\n", " ")[0:90]
        console.print(
            f"Plugin-[green]\\[guardian-post][/]\n  [white]risk={verdict.risk}\n  label={verdict.label}\n  output_preview={output_preview}[/]"
        )
    return verdicts


async def _run_guardian_pre_checks(
    payload: Any, risks: List[NexusRisk], inference_engine: str
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
    verdicts: List[GuardianVerdict] = await _call_guardian(
        HookStage.PRE, risks, input_text, inference_engine, assistant_text
    )
    for verdict in verdicts:
        input_preview = input_text.replace("\n", " ")[0:90]
        console.print(
            f"Plugin-[blue]\\[guardian-pre][/]\n  [white]risk={verdict.risk}\n  label={verdict.label}\n  input_preview={input_preview}[/]"
        )
    return verdicts


class GuardianPluginFactory:

    @staticmethod
    def create(guardian_mode: GuardianMode, *args, **kwargs) -> GuardianPlugin:
        guardian_plugin_class = (
            GuardianEnforcePlugin
            if guardian_mode == GuardianMode.ENFORCE
            else GuardianAuditPlugin
        )
        return guardian_plugin_class(*args, **kwargs)


class GuardianPlugin(BasePlugin):
    """Shared state and factory methods for Guardian plugins."""

    def __init__(self, risks: List[NexusRisk], inference_engine):
        """Create plugin from a Nexus PolicyManifest.

        Args:
            manifest: A PolicyManifest with guardian_risks and risk_names.
            enforce: If True, returns a GuardianEnforcePlugin (SEQUENTIAL mode)
                that blocks generation when risks are detected.
            inference_engine: The inference engine, defaults to Ollama
        """
        self.risks = risks
        self.all_verdicts: List[GuardianVerdict] = []
        self.inference_engine = inference_engine

    def register(self) -> None:
        native = [r for r in self.risks if r.is_native]
        custom = [r for r in self.risks if not r.is_native]
        LOGGER.info(
            f"Guardian plugin registered [{self._PLUGIN_MODE} mode]: {len(self.risks)} risks — {len(native)} native, {len(custom)} custom criteria"
        )
        super().register()

    def summary(self) -> Dict[str, List[GuardianVerdict]]:
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
        risks: List[NexusRisk],
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        super().__init__(risks, inference_engine)

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.AUDIT)
    async def check_input(self, payload: Any, ctx: Any) -> None:
        """Pre-generation: assess input prompt for risks (observe-only)."""
        verdicts = await _run_guardian_pre_checks(payload, self.risks, self.inference_engine)
        self.all_verdicts.extend(verdicts)

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.AUDIT)
    async def check_output(self, payload: Any, ctx: Any) -> None:
        """Post-generation: assess LLM output for risks (observe-only)."""
        verdicts = await _run_guardian_post_checks(payload, self.risks, self.inference_engine)
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

        result_summary = (
            "error" if not payload.success else f"{len(tool_output)} bytes"
        )
        LOGGER.info(
            f"[guardian-post-tool] {tool_name} — {result_summary}, {latency}ms"
        )

        if not (not tool_output or not payload.success):
            # Run Guardian checks on the tool output (treat as assistant text)
            verdicts: list[GuardianVerdict] = await _call_guardian(
                HookStage.TOOLS_POST,
                self.risks,
                input_text=f"Tool {tool_name} was called",
                assistant_text=tool_output[:2000],
                inference_engine=self.inference_engine,
                name_prefix="tool:",
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
        risks: List[NexusRisk],
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        super().__init__(risks, inference_engine)

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_input(self, payload: Any, ctx: Any) -> Any:
        """Pre-generation: block if input prompt has risks."""
        verdicts: List[GuardianVerdict] = await _run_guardian_pre_checks(
            payload, self.risks, self.inference_engine
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
                reason=f"Input risks assessment failed for {failed}",
                code="guardian_input_risk_failure",
                details={"failed_risks": failed, "stage": HookStage.PRE},
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-pre-enforce][/]\n  BLOCKING INPUT — risks flagged for {flagged}"
            )
            console.print()
            return block(
                reason=f"Input prompt triggered a Guardian risk detection in ENFORCE mode for {flagged}",
                code="guardian_input_risk_detected",
                details={"flagged_risks": flagged, "stage": HookStage.PRE},
            )
        return None

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_output(self, payload: Any, ctx: Any) -> Any:
        """Post-generation: block if LLM output has risks."""
        verdicts = await _run_guardian_post_checks(payload, self.risks, self.inference_engine)
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
                reason=f"Output risks assessment failed for {failed}",
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
                reason=f"An output generation triggered a Guardian risk detection in ENFORCE mode for {flagged}",
                code="guardian_output_risk_detected",
                details={"flagged_risks": flagged, "stage": HookStage.POST},
            )
        return None

    @hook(HookType.TOOL_PRE_INVOKE, mode=PluginMode.SEQUENTIAL)
    async def enforce_tool_input(self, payload: Any, ctx: Any) -> Any:
        """Pre-tool: log the tool call (enforcement reserved for post-invoke)."""
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        args = getattr(tool_call, "args", {})

        # Run Guardian checks on tool input
        verdicts: list[GuardianVerdict] = await _call_guardian(
            HookStage.TOOLS_PRE,
            self.risks,
            input_text=f"Tool {tool_name} was called with arguments: {json.dumps(args, indent=2)}",
            inference_engine=self.inference_engine,
            name_prefix="tool:",
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
                reason=f"Tool input risks assessment failed for {failed}",
                code="guardian_tool_output_risk_failure",
                details={
                    "failed_risks": failed,
                    "tool": tool_name,
                    "stage": HookStage.TOOLS_PRE,
                },
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL INPUT — risks in {tool_name}: {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected risks in Tool input - {tool_name}: {flagged}",
                code="guardian_tool_input_risk_detected",
                details={
                    "flagged_risks": flagged,
                    "tool": tool_name,
                    "stage": HookStage.TOOLS_PRE,
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

        # Run Guardian checks on tool output
        verdicts: list[GuardianVerdict] = await _call_guardian(
            HookStage.TOOLS_POST,
            self.risks,
            input_text=f"Tool {tool_name} was called",
            assistant_text=tool_output[:2000],
            inference_engine=self.inference_engine,
            name_prefix="tool:",
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
                reason=f"Tool output risks assessment failed for {failed}",
                code="guardian_tool_output_risk_failure",
                details={
                    "failed_risks": failed,
                    "tool": tool_name,
                    "stage": HookStage.TOOLS_POST,
                },
            )
        elif flagged:
            console.print()
            console.print(
                f"[yellow]Plugin-\\[guardian-post-tool-enforce][/]\n  BLOCKING TOOL OUTPUT — risks in {tool_name}: {flagged}"
            )
            console.print()
            return block(
                reason=f"Guardian detected risks in Tool output - {tool_name}: {flagged}",
                code="guardian_tool_output_risk_detected",
                details={
                    "flagged_risks": flagged,
                    "tool": tool_name,
                    "stage": HookStage.TOOLS_POST,
                },
            )
        return None
