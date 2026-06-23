"""Audit trail hook — records every pipeline event to a JSONL LOGGER.

Captures generation calls, Guardian verdicts, component lifecycle events,
and validation outcomes.  Designed to compose with GuardianAuditPlugin
(priority 40) — this hook runs at priority 100 so Guardian verdicts are
available in user_metadata by the time we LOGGER.

Usage:
    from audit_trail_hook import AuditTrailPlugin
    plugin = AuditTrailPlugin(log_path="audit.jsonl")
    register(plugin)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional, Union

from mellea.plugins import HookType, Plugin, PluginMode, hook

from mellea_skills_compiler.enums import GuardianScore
from mellea_skills_compiler.plugins import BasePlugin
from mellea_skills_compiler.plugins.guardian import (
    GuardianAuditPlugin,
    GuardianEnforcePlugin,
)
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


class AuditTrailPlugin(
    BasePlugin, Plugin, name="mellea_skills_compiler-audit-trail", priority=100
):
    """Append-only JSONL audit trail for GraniteClawHub PoC.

    Each entry contains:
      - timestamp, hook_type, session_id, request_id
      - event-specific data (prompt preview, output preview, verdicts, etc.)
      - optional policy_id for traceability to organisational policy

    The priority (100) ensures this runs after all transform/sequential hooks,
    so user_metadata is fully populated (e.g. Guardian verdicts at pri 40).
    """

    def __init__(
        self,
        log_path: Path,
        guardian_plugin: Optional[
            Union[
                GuardianAuditPlugin,
                GuardianEnforcePlugin,
            ]
        ] = None,
    ):
        self.guardian_plugin = guardian_plugin
        self.policy_id = f"nexus-{guardian_plugin.taxonomy}" if guardian_plugin else ""
        self._entries: list[dict] = []

        # audit log
        if log_path.exists():
            log_path.unlink()
        self.log_path = log_path

        LOGGER.info(f"Audit plugin registered - Trail path: {log_path}")

    def _write(self, entry: dict) -> None:
        entry["guardian_mode"] = self.guardian_plugin._PLUGIN_MODE
        entry["timestamp"] = datetime.now(UTC).isoformat()
        if self.policy_id:
            entry["policy_id"] = self.policy_id
        self._entries.append(entry)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    # ── Generation hooks ────────────────────────────────────────────
    @hook(HookType.GENERATION_PRE_CALL, mode=PluginMode.FIRE_AND_FORGET)
    async def log_pre_call(self, payload: Any, ctx: Any) -> None:
        """Log the prompt being sent to the LLM."""
        action = payload.action
        if action is None:
            return
        input_preview = dict(action.format_for_llm().args)

        verdicts = []
        if self.guardian_plugin is not None:
            # Read the most recent verdicts from the Guardian plugin directly
            recent = self.guardian_plugin.all_verdicts[
                -len(self.guardian_plugin.risks) :
            ]
            verdicts.extend(
                [
                    {
                        "risk": v.risk,
                        "label": v.label,
                        "raw": v.raw_output,
                        "ts": v.timestamp,
                    }
                    for v in recent
                ]
            )

        self._write(
            {
                "hook": "generation_pre_call",
                "session_id": getattr(payload, "session_id", ""),
                "request_id": getattr(payload, "request_id", ""),
                "component_type": type(payload.action).__name__,
                "input_preview": input_preview,
                "risk_detected": any(
                    v.get("label") == GuardianScore.YES for v in verdicts
                ),
                "risk_failed": any(
                    v.get("label") in [GuardianScore.FAILED, GuardianScore.ERROR]
                    for v in verdicts
                ),
                "guardian_verdicts": verdicts,
                "model_options": dict(getattr(payload, "model_options", {})),
            }
        )

    @hook(HookType.GENERATION_POST_CALL, mode=PluginMode.FIRE_AND_FORGET)
    async def log_post_call(self, payload: Any, ctx: Any) -> None:
        """Log LLM output and any Guardian verdicts."""
        model_output = payload.model_output
        output_text = getattr(model_output, "value", "") or "" if model_output else ""
        try:
            output_text = json.loads(output_text)
        except:
            pass
        latency = getattr(payload, "latency_ms", 0)

        verdicts = []
        if self.guardian_plugin is not None:
            # Read the most recent verdicts from the Guardian plugin directly
            recent = self.guardian_plugin.all_verdicts[
                -len(self.guardian_plugin.risks) :
            ]
            verdicts.extend(
                [
                    {
                        "risk": v.risk,
                        "label": v.label,
                        "raw": v.raw_output,
                        "ts": v.timestamp,
                    }
                    for v in recent
                ]
            )

        self._write(
            {
                "hook": "generation_post_call",
                "session_id": getattr(payload, "session_id", ""),
                "request_id": getattr(payload, "request_id", ""),
                "output_preview": output_text,
                "latency_ms": latency,
                "risk_detected": any(
                    v.get("label") == GuardianScore.YES for v in verdicts
                ),
                "risk_failed": any(
                    v.get("label") in [GuardianScore.FAILED, GuardianScore.ERROR]
                    for v in verdicts
                ),
                "guardian_verdicts": verdicts,
            }
        )

    # ── Component hooks ─────────────────────────────────────────────
    @hook(HookType.COMPONENT_PRE_EXECUTE, mode=PluginMode.FIRE_AND_FORGET)
    async def log_component_start(self, payload: Any, ctx: Any) -> None:
        self._write(
            {
                "hook": "component_pre_execute",
                "session_id": getattr(payload, "session_id", ""),
                "component_type": getattr(payload, "component_type", ""),
            }
        )

    @hook(HookType.COMPONENT_POST_SUCCESS, mode=PluginMode.FIRE_AND_FORGET)
    async def log_component_success(self, payload: Any, ctx: Any) -> None:
        self._write(
            {
                "hook": "component_post_success",
                "session_id": getattr(payload, "session_id", ""),
                "component_type": getattr(payload, "component_type", ""),
                "latency_ms": getattr(payload, "latency_ms", 0),
            }
        )

    @hook(HookType.COMPONENT_POST_ERROR, mode=PluginMode.FIRE_AND_FORGET)
    async def log_component_error(self, payload: Any, ctx: Any) -> None:
        self._write(
            {
                "hook": "component_post_error",
                "session_id": getattr(payload, "session_id", ""),
                "component_type": getattr(payload, "component_type", ""),
                "error": str(getattr(payload, "error", "")),
            }
        )

    # ── Validation hooks ────────────────────────────────────────────
    @hook(HookType.VALIDATION_POST_CHECK, mode=PluginMode.FIRE_AND_FORGET)
    async def log_validation(self, payload: Any, ctx: Any) -> None:
        self._write(
            {
                "hook": "validation_post_check",
                "session_id": getattr(payload, "session_id", ""),
                "passed": getattr(payload, "passed", None),
                "reason": getattr(payload, "reason", ""),
            }
        )

    # ── Tool hooks (Pattern 3: LLM-directed tool calls) ──────────
    @hook(HookType.TOOL_PRE_INVOKE, mode=PluginMode.FIRE_AND_FORGET)
    async def log_tool_pre(self, payload: Any, ctx: Any) -> None:
        """Log tool call before execution."""
        tool_call = payload.model_tool_call
        self._write(
            {
                "hook": "tool_pre_invoke",
                "session_id": getattr(payload, "session_id", ""),
                "tool_name": getattr(tool_call, "name", "unknown"),
                "tool_args": str(getattr(tool_call, "args", {})),
                "governance": "pattern3_llm_directed",
            }
        )

    @hook(HookType.TOOL_POST_INVOKE, mode=PluginMode.FIRE_AND_FORGET)
    async def log_tool_post(self, payload: Any, ctx: Any) -> None:
        """Log tool result after execution."""
        tool_call = payload.model_tool_call
        tool_name = getattr(tool_call, "name", "unknown")
        tool_output = str(payload.tool_output or "")

        # Check for Guardian verdicts on tool output
        verdicts = []
        if self.guardian_plugin is not None:
            # Look for tool-prefixed verdicts added by Guardian
            recent = [
                v
                for v in self.guardian_plugin.all_verdicts
                if v.risk.startswith("tool:")
            ]
            verdicts.extend(
                [
                    {
                        "risk": v.risk,
                        "label": v.label,
                        "raw": v.raw_output,
                        "ts": v.timestamp,
                    }
                    for v in recent[-len(getattr(self.guardian_plugin, "risks", [])) :]
                ]
            )

        self._write(
            {
                "hook": "tool_post_invoke",
                "session_id": getattr(payload, "session_id", ""),
                "tool_name": tool_name,
                "tool_args": str(getattr(tool_call, "args", {})),
                "output_preview": tool_output,
                "execution_time_ms": payload.execution_time_ms,
                "success": payload.success,
                "error": str(payload.error) if payload.error else "",
                "guardian_verdicts": verdicts,
                "risk_detected": any(
                    v.get("label") == GuardianScore.YES for v in verdicts
                ),
                "risk_failed": any(
                    v.get("label") in [GuardianScore.FAILED, GuardianScore.ERROR]
                    for v in verdicts
                ),
                "governance": "pattern3_llm_directed",
            }
        )

    # ── Summary ─────────────────────────────────────────────────────
    def summary(self) -> dict:
        """Return a summary of the audit trail for display."""
        total = len(self._entries)
        generations = [e for e in self._entries if e["hook"].startswith("generation")]
        tool_calls = [e for e in self._entries if e["hook"].startswith("tool")]
        gen_risks_flagged = [e for e in generations if e.get("risk_detected")]
        gen_risks_failed = [e for e in generations if e.get("risk_failed")]
        tool_risks = [e for e in tool_calls if e.get("risk_detected")]
        tool_risks_failed = [e for e in tool_calls if e.get("risk_failed")]
        return {
            "total_events": total,
            "generations": len(generations),
            "tool_calls": len(tool_calls),
            "generation_risks_flagged": len(gen_risks_flagged),
            "generation_risks_failed": len(gen_risks_failed),
            "tool_risks_flagged": len(tool_risks),
            "tool_risks_failed": len(tool_risks_failed),
            "log_file": str(self.log_path),
        }
