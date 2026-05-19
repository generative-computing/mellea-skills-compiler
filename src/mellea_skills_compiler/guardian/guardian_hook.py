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

Usage (Nexus-driven — risks from policy manifest):
    from nexus_policy import generate_policy_manifest
    manifest = generate_policy_manifest("An AI agent that...")
    plugin = GuardianAuditPlugin.from_manifest(manifest, enforce=True)
    register(plugin)
"""

from __future__ import annotations

import logging
import urllib.error
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from mellea.plugins import HookType, Plugin, PluginMode, hook
from mellea.plugins.registry import block

from mellea_skills_compiler.enums import InferenceEngineType
from mellea_skills_compiler.inference import InferenceService
from mellea_skills_compiler.toolkit.logging import configure_logger


log = configure_logger("MelleaSkills.guardian_hook")


@dataclass
class GuardianVerdict:
    """Result of a single Guardian risk check."""

    risk: str
    label: str  # "Yes" (risk detected), "No" (safe), "Failed"
    raw_output: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _parse_guardian_score(text: str) -> str:
    """Extract Yes/No from Guardian <score> tags."""
    s = text.lower()
    if "<score>" in s and "</score>" in s:
        score = s.split("<score>")[1].split("</score>")[0].strip()
        if score == "yes":
            return "Yes"
        if score == "no":
            return "No"
    return "Failed"


def _call_guardian(
    user_text: str,
    risk: str,
    assistant_text: Optional[str] = None,
    guardian_model: Optional[str] = None,
    inference_engine: Optional[str] = None,
) -> GuardianVerdict:
    """Synchronous call to Guardian.

    Guardian expects a chat with the user turn (+ optional assistant turn)
    and a system prompt specifying the risk to evaluate.

    The ``risk`` parameter is the Guardian system prompt content:
      - For native risks (from Nexus ``tag`` field): a bare risk name like
        ``"harm"``, ``"social_bias"``, ``"jailbreak"`` — Guardian uses its
        calibrated assessment path for these.
      - For custom criteria (no Nexus ``tag``): description text
        sent as free-form custom criteria.

    This distinction is set upstream in ``nexus_policy.py`` via the
    two-tier calling convention (see NexusRisk.is_native).

    When assistant_text is None, this is a pre-generation check on the
    input prompt only (the GAF-Guard pattern). When assistant_text is
    provided, this is a post-generation check on the output.

    Guardian response format: ``<score>yes</score>`` (risk detected) or
    ``<score>no</score>`` (safe).
    """
    messages = [{"role": "system", "content": risk}]
    if user_text:
        messages.append({"role": "user", "content": user_text})
    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})

    try:
        guardian = InferenceService(inference_engine).guardian(
            guardian_model, parameters={"temperature": 0}
        )
        raw_prediction = guardian.chat([messages], verbose=False)[0].prediction
        label = _parse_guardian_score(raw_prediction)
        return GuardianVerdict(risk=risk, label=label, raw_output=raw_prediction)
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as e:
        log.warning("Guardian call failed for risk=%s: %s", risk, e)
        return GuardianVerdict(risk=risk, label="Failed", raw_output=str(e))


def _run_guardian_checks(
    plugin: _GuardianBase, payload: Any, guardian_model: str, inference_engine: str
) -> tuple[list[GuardianVerdict], list[str]]:
    """Shared logic: run Guardian checks and return (verdicts, flagged_labels)."""
    mot = payload.model_output
    if mot is None:
        return [], []

    assistant_text = getattr(mot, "value", None) or ""
    if not assistant_text:
        return [], []

    # Reconstruct the user prompt from the payload
    prompt = payload.prompt
    if isinstance(prompt, list):
        user_text = ""
        for msg in reversed(list(prompt)):
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_text = msg.get("content", "")
                break
    else:
        user_text = str(prompt) if prompt else ""

    verdicts: list[GuardianVerdict] = []
    flagged: list[str] = []
    for risk_prompt, risk_label in zip(plugin.risks, plugin.risk_labels):
        verdict = _call_guardian(
            user_text, risk_prompt, assistant_text, guardian_model, inference_engine
        )
        verdict.risk = risk_label
        verdicts.append(verdict)
        level = logging.WARNING if verdict.label == "Yes" else logging.INFO
        log.log(
            level,
            "[guardian] risk=%s label=%s output_preview=%.60s",
            risk_label,
            verdict.label,
            assistant_text.replace("\n", " "),
        )
        if verdict.label == "Yes":
            flagged.append(risk_label)

    plugin.all_verdicts.extend(verdicts)

    # Stash verdicts in user_metadata for audit_trail_hook to pick up
    meta = dict(payload.user_metadata)
    meta["guardian_verdicts"] = [
        {"risk": v.risk, "label": v.label, "raw": v.raw_output, "ts": v.timestamp}
        for v in verdicts
    ]

    return verdicts, flagged


def _run_guardian_pre_checks(
    plugin: _GuardianBase, payload: Any, guardian_model: str, inference_engine: str
) -> tuple[list[GuardianVerdict], list[str]]:
    """Pre-generation check: assess the input prompt before LLM generation.

    Follows the GAF-Guard pattern — system + user only, no assistant turn.
    """
    # Extract user text from the action (CBlock or Component/Instruction)
    action = payload.action
    if action is None:
        return [], []
    # Instruction stores text in _description (a CBlock); CBlock has .value
    inner = (
        getattr(action, "description", None)
        or getattr(action, "_description", None)
        or getattr(action, "_arguments", None)
        or action
    )
    user_text = getattr(inner, "value", None) or str(inner)
    if not user_text:
        return [], []

    verdicts: list[GuardianVerdict] = []
    flagged: list[str] = []
    for risk_prompt, risk_label in zip(plugin.risks, plugin.risk_labels):
        verdict = _call_guardian(
            user_text, risk_prompt, None, guardian_model, inference_engine
        )  # no assistant text
        verdict.risk = risk_label
        verdicts.append(verdict)
        level = logging.WARNING if verdict.label == "Yes" else logging.INFO
        log.log(
            level,
            "[guardian-pre] risk=%s label=%s input_preview=%.60s",
            risk_label,
            verdict.label,
            user_text.replace("\n", " "),
        )
        if verdict.label == "Yes":
            flagged.append(risk_label)

    plugin.all_verdicts.extend(verdicts)
    return verdicts, flagged


class _GuardianBase:
    """Shared state and factory methods for Guardian plugins."""

    def __init__(
        self,
        risks: Optional[list[str]] = None,
        risk_labels: Optional[list[str]] = None,
        guardian_model: Optional[str] = None,
        inference_engine: Optional[InferenceEngineType] = None,
    ):
        self.risks = risks or ["harm", "social_bias", "jailbreak"]
        self.risk_labels = risk_labels or self.risks
        self.all_verdicts: list[GuardianVerdict] = []
        self.guardian_model = guardian_model
        self.inference_engine = inference_engine


class GuardianAuditPlugin(
    _GuardianBase, Plugin, name="granite-guardian-audit", priority=40
):
    """Observe-only Guardian hook (AUDIT mode).

    Scans every LLM output against Granite Guardian risk checks.
    Verdicts are logged and stored but generation is never blocked.

    For enforcement mode, use ``GuardianAuditPlugin.from_manifest(manifest, enforce=True)``
    which returns a ``GuardianEnforcePlugin`` instead.
    """

    @classmethod
    def from_manifest(
        cls,
        manifest: Any,
        enforce: bool = False,
        guardian_model: Optional[str] = None,
        inference_engine: InferenceEngineType = InferenceEngineType.OLLAMA,
    ) -> GuardianAuditPlugin | GuardianEnforcePlugin:
        """Create a plugin from a Nexus PolicyManifest.

        Args:
            manifest: A PolicyManifest with guardian_risks and risk_names.
            enforce: If True, returns a GuardianEnforcePlugin (SEQUENTIAL mode)
                that blocks generation when risks are detected.
            guardian_model: The guardian model
            inference_engine: The inference engine, defaults to Ollama
        """
        # Log tier breakdown for transparency
        native = [r for r in manifest.risks if r.is_native]
        custom = [r for r in manifest.risks if not r.is_native]
        mode_label = "ENFORCE" if enforce else "AUDIT"
        log.info(
            "Guardian plugin (%s): %d risks — %d native, %d custom criteria",
            mode_label,
            len(manifest.risks),
            len(native),
            len(custom),
        )
        for r in native:
            log.info("  [native]  %s → %s", r.name, r.guardian_prompt)
        for r in custom:
            log.info("  [custom]  %s → %.60s", r.name, r.guardian_prompt)

        target_cls = GuardianEnforcePlugin if enforce else cls
        return target_cls(
            risks=manifest.guardian_risks,
            risk_labels=manifest.risk_names,
            guardian_model=guardian_model,
            inference_engine=inference_engine,
        )

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.AUDIT)
    async def check_input(self, payload: Any, ctx: Any) -> None:
        """Pre-generation: assess input prompt for risks (observe-only)."""
        _run_guardian_pre_checks(
            self, payload, self.guardian_model, self.inference_engine
        )

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.AUDIT)
    async def check_output(self, payload: Any, ctx: Any) -> None:
        """Post-generation: assess LLM output for risks (observe-only)."""
        _run_guardian_checks(self, payload, self.guardian_model, self.inference_engine)

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
        log.info("[guardian-tool] PRE_INVOKE %s(%s)", tool_name, str(args)[:100])

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

        if not tool_output or not payload.success:
            log.info(
                "[guardian-tool] POST_INVOKE %s — %s, %dms",
                tool_name,
                "error" if not payload.success else "empty",
                latency,
            )
            return

        log.info(
            "[guardian-tool] POST_INVOKE %s — %d bytes, %dms",
            tool_name,
            len(tool_output),
            latency,
        )

        # Run Guardian checks on the tool output (treat as assistant text)
        verdicts: list[GuardianVerdict] = []
        for risk_prompt, risk_label in zip(self.risks, self.risk_labels):
            verdict = _call_guardian(
                user_text=f"Tool {tool_name} was called",
                risk=risk_prompt,
                assistant_text=tool_output[:2000],
                guardian_model=self.guardian_model,
                inference_engine=self.inference_engine,
            )
            verdict.risk = f"tool:{risk_label}"
            verdicts.append(verdict)
            if verdict.label == "Yes":
                log.warning(
                    "[guardian-tool] RISK in %s output: %s", tool_name, risk_label
                )

        self.all_verdicts.extend(verdicts)


class GuardianEnforcePlugin(
    _GuardianBase, Plugin, name="granite-guardian-enforce", priority=40
):
    """Enforcement Guardian hook (SEQUENTIAL mode).

    Scans every LLM output against Granite Guardian risk checks.
    If any risk is flagged, returns block() to halt the pipeline
    with a PluginViolationError.
    """

    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_input(self, payload: Any, ctx: Any) -> Any:
        """Pre-generation: block if input prompt has risks."""
        verdicts, flagged = _run_guardian_pre_checks(
            self, payload, self.guardian_model, self.inference_engine
        )
        if flagged:
            risk_list = ", ".join(flagged)
            log.warning(
                "[guardian-enforce] BLOCKING INPUT — risks flagged: %s", risk_list
            )
            return block(
                reason=f"Guardian detected input risks: {risk_list}",
                code="guardian_input_risk_detected",
                details={"flagged_risks": flagged, "stage": "pre_generation"},
            )
        return None

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.SEQUENTIAL)
    async def enforce_output(self, payload: Any, ctx: Any) -> Any:
        """Post-generation: block if LLM output has risks."""
        verdicts, flagged = _run_guardian_checks(
            self, payload, self.guardian_model, self.inference_engine
        )
        if flagged:
            risk_list = ", ".join(flagged)
            log.warning(
                "[guardian-enforce] BLOCKING OUTPUT — risks flagged: %s", risk_list
            )
            return block(
                reason=f"Guardian detected output risks: {risk_list}",
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
        log.info(
            "[guardian-enforce-tool] PRE_INVOKE %s(%s)", tool_name, str(args)[:100]
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
        flagged: list[str] = []
        for risk_prompt, risk_label in zip(self.risks, self.risk_labels):
            verdict = _call_guardian(
                user_text=f"Tool {tool_name} was called",
                risk=risk_prompt,
                assistant_text=tool_output[:2000],
                guardian_model=self.guardian_model,
                inference_engine=self.inference_engine,
            )
            verdict.risk = f"tool:{risk_label}"
            self.all_verdicts.append(verdict)
            if verdict.label == "Yes":
                flagged.append(risk_label)

        if flagged:
            risk_list = ", ".join(flagged)
            log.warning(
                "[guardian-enforce-tool] BLOCKING — risks in %s output: %s",
                tool_name,
                risk_list,
            )
            return block(
                reason=f"Guardian detected risks in tool output ({tool_name}): {risk_list}",
                code="guardian_tool_risk_detected",
                details={
                    "flagged_risks": flagged,
                    "tool": tool_name,
                    "stage": "post_tool",
                },
            )
        return None
