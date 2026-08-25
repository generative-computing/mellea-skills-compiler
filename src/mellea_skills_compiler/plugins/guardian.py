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
import threading
from copy import deepcopy
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
    hook_stage: HookStage,
    risks: List[NexusRisk],
    input_text: str,
    inference_engine,
    assistant_text: Optional[str] = None,
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
        # Batch inferencing guardian risks
        raw_predictions = [
            raw_prediction.prediction
            for raw_prediction in inference_engine.chat(all_messages, verbose=False)
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
                preview_source = assistant_text if assistant_text else input_text
                preview = preview_source.replace("\n", " ")[0:90]
                console.print(
                    f'[white]  risk={messages[0]["content"]}\n  label={label}\n  preview={preview}[/]'
                )

                try:
                    raw_prediction = inference_engine.chat([messages], verbose=False)[
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
            GuardianVerdict(
                risk=risk_name,
                label=label,
                raw_output=raw_prediction,
                hook_stage=hook_stage,
            )
        )

    return verdicts


def _get_thunk_action(model_output: Any) -> Any:
    """Return the originating action of a ``ModelOutputThunk``, or ``None``.

    On mellea 0.7+ the action lives at ``thunk._call.action`` (see
    ``_CallInfo`` in ``mellea/core/base.py``); on <0.7 it was on
    ``thunk._action``. Both paths are private, but the dual accessor lets
    us survive the rename without wire-level knowledge of which mellea we
    are running against. This is a fallback for the id-correlation path
    below — if ``payload.generation_id`` is populated (0.7+) we prefer
    that.
    """
    call = getattr(model_output, "_call", None)
    if call is not None:
        return getattr(call, "action", None)
    return getattr(model_output, "_action", None)


def _run_guardian_post_checks(
    plugin: "GuardianPlugin",
    payload: Any,
    risks: List[NexusRisk],
    inference_engine: str,
) -> List[GuardianVerdict]:
    """Shared logic: run Guardian checks and return (verdicts, flagged_labels).

    Requirement-driven generations are skipped — they are validation calls
    not user-facing outputs, and the surrounding pipeline monitors their
    downstream results instead. On mellea 0.7+ this uses id correlation via
    ``payload.generation_id`` (recorded by ``_run_guardian_pre_checks`` when
    it saw a Requirement action); on <0.7 or when no id is available it
    falls back to reading ``_call.action`` / ``_action`` from the thunk.
    """
    model_output = payload.model_output
    if model_output is None:
        return []

    generation_id = getattr(payload, "generation_id", None)
    if generation_id is not None:
        # Lock-guarded to match the surrounding ``_verdict_lock`` discipline
        # and to survive a free-threaded interpreter (PEP 703). CPython's GIL
        # makes single ``set.__contains__`` / ``set.discard`` atomic today,
        # but the read+discard pair is not.
        with plugin._verdict_lock:
            if generation_id in plugin._requirement_generation_ids:
                plugin._requirement_generation_ids.discard(generation_id)
                return []

    # Belt-and-braces: on pre-0.7 mellea, or if the pre-call hook did not
    # fire for any reason, still catch Requirement-driven generations.
    action = _get_thunk_action(model_output)
    if isinstance(action, Requirement):
        # Only WARN when generation_id is populated — that's the real
        # regression signal (hook ordering changed on a supported mellea
        # version). generation_id is None is the expected pre-0.7 shape
        # and does not indicate any bug.
        if generation_id is not None:
            LOGGER.warning(
                "Guardian post-check: Requirement action reached the post-call hook "
                "without a matching pre-call tag (generation_id=%s). Falling back to "
                "the thunk-action inspection path; a future mellea hook-ordering "
                "change may be masking this. Investigate if this recurs.",
                generation_id,
            )
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
        HookStage.POST, risks, input_text, inference_engine, assistant_text
    )
    for verdict in verdicts:
        output_preview = assistant_text.replace("\n", " ")[0:90]
        console.print(
            f"Plugin-[green]\\[guardian-post][/]\n  [white]risk={verdict.risk}\n  label={verdict.label}\n  output_preview={output_preview}[/]"
        )
    return verdicts


def _run_guardian_pre_checks(
    plugin: "GuardianPlugin",
    payload: Any,
    risks: List[NexusRisk],
    inference_engine: str,
) -> List[GuardianVerdict]:
    """Pre-generation check: assess the input prompt before LLM generation.

    Follows the GAF-Guard pattern — system + user only, no assistant turn.
    Records ``payload.generation_id`` for Requirement-driven generations so
    the paired post-call hook can skip them without inspecting private
    attributes on the thunk.
    """

    # Extract action from the CBlock or Component/Instruction
    action = payload.action
    if action is None:
        return []

    # Requirement early-exit BEFORE any ``format_for_llm()`` call —
    # ``Requirement.format_for_llm`` asserts it runs inside a validate() call
    # for that same requirement (see mellea/core/requirement.py:format_for_llm),
    # and raises AssertionError otherwise. Guardian's plugin runs outside any
    # such context. Recording the id here lets the paired post-call hook skip
    # the corresponding output without reaching into ``ModelOutputThunk``.
    if isinstance(action, Requirement):
        generation_id = getattr(payload, "generation_id", None)
        if generation_id is not None:
            # Lock-guarded — see the paired discard in _run_guardian_post_checks.
            with plugin._verdict_lock:
                plugin._requirement_generation_ids.add(generation_id)
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
        # Per-generation-id verdict map — populated by every _call_guardian invocation
        # and read by AuditTrailPlugin.log_pre_call/log_post_call/log_tool_post so
        # correlation is id-based rather than positional. Guards mellea 0.7's
        # #1175 parallel sampling.
        self.verdicts_by_generation_id: Dict[str, List[GuardianVerdict]] = {}
        self._verdict_lock = threading.RLock()
        # Ids of Requirement-driven generations recorded in check_input/enforce_input.
        # Drained by the paired post-call hook so it can skip without reaching into
        # ModelOutputThunk private attributes.
        self._requirement_generation_ids: set[str] = set()
        self.inference_engine = inference_engine

    def _record_verdicts(
        self, verdicts: List[GuardianVerdict], generation_id: Optional[str]
    ) -> None:
        """Thread-safe append to ``all_verdicts`` plus id-keyed indexing."""
        if not verdicts:
            return
        with self._verdict_lock:
            self.all_verdicts.extend(verdicts)
            if generation_id is not None:
                self.verdicts_by_generation_id.setdefault(
                    generation_id, []
                ).extend(verdicts)

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
        verdicts = _run_guardian_pre_checks(
            self, payload, self.risks, self.inference_engine
        )
        self._record_verdicts(verdicts, getattr(payload, "generation_id", None))

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.AUDIT)
    async def check_output(self, payload: Any, ctx: Any) -> None:
        """Post-generation: assess LLM output for risks (observe-only)."""
        verdicts = _run_guardian_post_checks(
            self, payload, self.risks, self.inference_engine
        )
        self._record_verdicts(verdicts, getattr(payload, "generation_id", None))

    @hook(HookType.GENERATION_ERROR, mode=PluginMode.AUDIT)
    async def check_error(self, payload: Any, ctx: Any) -> None:
        """Generation error: record that the generation failed with no verdict.

        Added in mellea 0.7 (#1307 makes ``ModelOutputThunk.error`` public).
        Guardian assesses nothing here — a failed generation has no output
        to score — but recording an ERROR verdict per risk keeps the audit
        trail complete and preserves "every generation monitored" as a
        truthful claim.
        """
        generation_id = getattr(payload, "generation_id", None)
        verdicts = [
            GuardianVerdict(
                risk=risk.name,
                label=GuardianScore.ERROR,
                raw_output=str(getattr(payload, "error", "")),
                hook_stage=HookStage.POST,
            )
            for risk in self.risks
        ]
        self._record_verdicts(verdicts, generation_id)

    @hook(HookType.GENERATION_BATCH_PRE_CALL, mode=PluginMode.AUDIT)
    async def check_batch_input(self, payload: Any, ctx: Any) -> None:
        """Pre-batch generation: no-op — Requirement metadata isn't on batch payloads.

        Subscribed so a batch generation is visible to the plugin runner (and
        so ``AuditTrailPlugin.log_batch_pre_call`` fires alongside), but there
        is no per-item action metadata to filter on — ``generate_from_raw``
        code paths don't wrap Requirements. All assessment happens on the
        batch outputs in ``check_batch_output``.
        """
        return None

    @hook(HookType.GENERATION_BATCH_POST_CALL, mode=PluginMode.AUDIT)
    async def check_batch_output(self, payload: Any, ctx: Any) -> None:
        """Post-batch generation: assess each item's output (observe-only)."""
        model_outputs = getattr(payload, "model_outputs", None) or []
        generation_ids = getattr(payload, "generation_ids", None) or [None] * len(
            model_outputs
        )
        prompts = getattr(payload, "prompts", None) or [""] * len(model_outputs)
        for model_output, gen_id, prompt in zip(model_outputs, generation_ids, prompts):
            if model_output is None:
                continue
            assistant_text = getattr(model_output, "value", None) or ""
            if not assistant_text:
                continue
            input_text = str(prompt) if prompt else ""
            verdicts = _call_guardian(
                HookStage.POST, self.risks, input_text, self.inference_engine, assistant_text
            )
            self._record_verdicts(verdicts, gen_id)

    @hook(HookType.GENERATION_BATCH_ERROR, mode=PluginMode.AUDIT)
    async def check_batch_error(self, payload: Any, ctx: Any) -> None:
        """Batch generation error: record an ERROR verdict per risk per item.

        Symmetrical to ``check_error`` — a batch that raised produces no
        outputs to assess, but the audit trail records that the batch
        was attempted and failed.
        """
        generation_ids = getattr(payload, "generation_ids", None) or [None]
        for gen_id in generation_ids:
            verdicts = [
                GuardianVerdict(
                    risk=risk.name,
                    label=GuardianScore.ERROR,
                    raw_output=str(getattr(payload, "error", "")),
                    hook_stage=HookStage.POST,
                )
                for risk in self.risks
            ]
            self._record_verdicts(verdicts, gen_id)

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

            tool_risks = []
            for risk in self.risks:
                tool_risk = deepcopy(risk)
                tool_risk.name = f"tool:{tool_risk.name}"
                tool_risks.append(tool_risk)

            # Run Guardian checks on the tool output (treat as assistant text)
            verdicts: list[GuardianVerdict] = _call_guardian(
                HookStage.TOOLS_POST,
                tool_risks,
                input_text=f"Tool {tool_name} was called",
                assistant_text=tool_output[:2000],
                inference_engine=self.inference_engine,
            )
            # Tool calls carry their own correlation id in mellea 0.7; fall back
            # to the associated generation_id if only that is available.
            tool_correlation_id = getattr(payload, "tool_call_id", None) or getattr(
                payload, "generation_id", None
            )
            self._record_verdicts(verdicts, tool_correlation_id)

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
        verdicts: List[GuardianVerdict] = _run_guardian_pre_checks(
            self, payload, self.risks, self.inference_engine
        )
        self._record_verdicts(verdicts, getattr(payload, "generation_id", None))

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
        verdicts = _run_guardian_post_checks(
            self, payload, self.risks, self.inference_engine
        )
        self._record_verdicts(verdicts, getattr(payload, "generation_id", None))

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

        tool_risks = []
        for risk in self.risks:
            tool_risk = deepcopy(risk)
            tool_risk.name = f"tool:{tool_risk.name}"
            tool_risks.append(tool_risk)

        # Run Guardian checks on tool input
        verdicts: list[GuardianVerdict] = _call_guardian(
            HookStage.TOOLS_PRE,
            tool_risks,
            input_text=f"Tool {tool_name} was called with arguments: {json.dumps(args, indent=2)}",
            inference_engine=self.inference_engine,
        )
        tool_correlation_id = getattr(payload, "tool_call_id", None) or getattr(
            payload, "generation_id", None
        )
        self._record_verdicts(verdicts, tool_correlation_id)

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

        tool_risks = []
        for risk in self.risks:
            tool_risk = deepcopy(risk)
            tool_risk.name = f"tool:{tool_risk.name}"
            tool_risks.append(tool_risk)

        # Run Guardian checks on tool output
        verdicts: list[GuardianVerdict] = _call_guardian(
            HookStage.TOOLS_POST,
            tool_risks,
            input_text=f"Tool {tool_name} was called",
            assistant_text=tool_output[:2000],
            inference_engine=self.inference_engine,
        )
        tool_correlation_id = getattr(payload, "tool_call_id", None) or getattr(
            payload, "generation_id", None
        )
        self._record_verdicts(verdicts, tool_correlation_id)

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

    @hook(HookType.GENERATION_ERROR, mode=PluginMode.AUDIT)
    async def enforce_error(self, payload: Any, ctx: Any) -> None:
        """Generation error: record an ERROR verdict per risk.

        SEQUENTIAL enforcement is meaningless on an error path — there is no
        output to block. AUDIT mode is used deliberately so failed
        generations still leave an audit record. See ``check_error`` on
        :class:`GuardianAuditPlugin`.
        """
        generation_id = getattr(payload, "generation_id", None)
        verdicts = [
            GuardianVerdict(
                risk=risk.name,
                label=GuardianScore.ERROR,
                raw_output=str(getattr(payload, "error", "")),
                hook_stage=HookStage.POST,
            )
            for risk in self.risks
        ]
        self._record_verdicts(verdicts, generation_id)

    @hook(HookType.GENERATION_BATCH_PRE_CALL, mode=PluginMode.AUDIT)
    async def enforce_batch_input(self, payload: Any, ctx: Any) -> None:
        """Pre-batch generation: observed only. See ``check_batch_input``."""
        # Batch path does not surface per-item action metadata, so we do not
        # attempt to enforce on it. Kept as AUDIT mode so the batch is still
        # visible to the audit trail. Escalation to SEQUENTIAL blocking on
        # batch outputs requires per-item context we do not have here.
        return None

    @hook(HookType.GENERATION_BATCH_POST_CALL, mode=PluginMode.AUDIT)
    async def enforce_batch_output(self, payload: Any, ctx: Any) -> None:
        """Post-batch generation: assess each item and record verdicts.

        We deliberately do NOT block on batch outputs: the batch path is
        used by budget-forcing sampling where blocking would kill the
        sampling loop. Verdicts are recorded so the certifier can flag the
        run post-hoc.
        """
        model_outputs = getattr(payload, "model_outputs", None) or []
        generation_ids = getattr(payload, "generation_ids", None) or [None] * len(
            model_outputs
        )
        prompts = getattr(payload, "prompts", None) or [""] * len(model_outputs)
        for model_output, gen_id, prompt in zip(model_outputs, generation_ids, prompts):
            if model_output is None:
                continue
            assistant_text = getattr(model_output, "value", None) or ""
            if not assistant_text:
                continue
            input_text = str(prompt) if prompt else ""
            verdicts = _call_guardian(
                HookStage.POST, self.risks, input_text, self.inference_engine, assistant_text
            )
            self._record_verdicts(verdicts, gen_id)

    @hook(HookType.GENERATION_BATCH_ERROR, mode=PluginMode.AUDIT)
    async def enforce_batch_error(self, payload: Any, ctx: Any) -> None:
        """Batch generation error: record ERROR verdicts."""
        generation_ids = getattr(payload, "generation_ids", None) or [None]
        for gen_id in generation_ids:
            verdicts = [
                GuardianVerdict(
                    risk=risk.name,
                    label=GuardianScore.ERROR,
                    raw_output=str(getattr(payload, "error", "")),
                    hook_stage=HookStage.POST,
                )
                for risk in self.risks
            ]
            self._record_verdicts(verdicts, gen_id)
