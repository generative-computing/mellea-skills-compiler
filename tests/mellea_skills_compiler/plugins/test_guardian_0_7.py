"""Regression tests for the mellea 0.7 Guardian upgrade.

Covers:
  - The ``_action`` -> ``_call.action`` refactor: post-checks no longer
    reach into a private attribute and skip Requirement-driven generations
    via id correlation instead.
  - Concurrency safety of ``all_verdicts.extend`` / ``verdicts_by_generation_id``
    under the parallel sampling introduced in mellea PR #1175.
  - The new ``GENERATION_ERROR`` and ``GENERATION_BATCH_*`` hook handlers
    on both plugins.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mellea_skills_compiler.enums import GovernanceTaxonomy, GuardianScore, HookStage
from mellea_skills_compiler.models import GuardianVerdict, NexusRisk
from mellea_skills_compiler.plugins.guardian import (
    GuardianAuditPlugin,
    GuardianEnforcePlugin,
    _get_thunk_action,
)


def _risk(name: str) -> NexusRisk:
    return NexusRisk(
        name=name,
        description=f"{name} risk",
        guardian_prompt=name,
        source="test",
        is_native=True,
        taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
    )


@pytest.fixture
def audit_plugin() -> GuardianAuditPlugin:
    return GuardianAuditPlugin(risks=[_risk("harm"), _risk("jailbreak")])


@pytest.fixture
def enforce_plugin() -> GuardianEnforcePlugin:
    return GuardianEnforcePlugin(risks=[_risk("harm")])


class TestThunkActionAccess:
    """Ensures the dual-path accessor survives the 0.7 refactor."""

    def test_dual_path_reads_from_call_action_on_0_7(self):
        thunk = SimpleNamespace(_call=SimpleNamespace(action="the-action"))
        assert _get_thunk_action(thunk) == "the-action"

    def test_dual_path_falls_back_to_underscore_action_on_legacy(self):
        thunk = SimpleNamespace(_action="legacy-action")
        # No ``_call`` at all — pre-0.7 shape.
        assert _get_thunk_action(thunk) == "legacy-action"

    def test_dual_path_returns_none_when_neither_present(self):
        thunk = SimpleNamespace()
        assert _get_thunk_action(thunk) is None


class TestIdCorrelation:
    """Requirement-driven generations are skipped via generation_id, not private attrs."""

    def test_pre_call_records_requirement_generation_id(self, audit_plugin):
        from mellea.core.requirement import Requirement

        req = Requirement(description="must be nice")
        payload = SimpleNamespace(
            action=req,
            generation_id="gen-abc",
        )
        from mellea_skills_compiler.plugins import guardian as gmod

        gmod._run_guardian_pre_checks(
            audit_plugin, payload, audit_plugin.risks, "ollama"
        )
        assert "gen-abc" in audit_plugin._requirement_generation_ids

    def test_post_call_skips_recorded_id_without_reading_action(self, audit_plugin):
        from mellea_skills_compiler.plugins import guardian as gmod

        audit_plugin._requirement_generation_ids.add("gen-xyz")
        model_output = SimpleNamespace(
            _call=SimpleNamespace(action="not-a-req"),
            value="assistant text",
        )
        payload = SimpleNamespace(
            model_output=model_output,
            generation_id="gen-xyz",
            prompt="what?",
        )
        result = gmod._run_guardian_post_checks(
            audit_plugin, payload, audit_plugin.risks, "ollama"
        )
        assert result == []
        assert "gen-xyz" not in audit_plugin._requirement_generation_ids

    def test_post_call_falls_back_to_action_check_when_id_absent(self, audit_plugin):
        """Belt-and-braces: pre-0.7 payloads with no generation_id still skip Requirements."""
        from mellea.core.requirement import Requirement
        from mellea_skills_compiler.plugins import guardian as gmod

        req = Requirement(description="must be nice")
        model_output = SimpleNamespace(_call=SimpleNamespace(action=req), value="x")
        payload = SimpleNamespace(
            model_output=model_output, generation_id=None, prompt=""
        )
        result = gmod._run_guardian_post_checks(
            audit_plugin, payload, audit_plugin.risks, "ollama"
        )
        assert result == []


class TestRecordVerdictsIndexing:
    """_record_verdicts populates both ``all_verdicts`` and the id-map."""

    def test_indexes_by_generation_id(self, audit_plugin):
        v = GuardianVerdict(risk="harm", label=GuardianScore.NO, raw_output="ok", hook_stage=HookStage.POST)
        audit_plugin._record_verdicts([v], generation_id="gen-1")
        assert v in audit_plugin.all_verdicts
        assert audit_plugin.verdicts_by_generation_id["gen-1"] == [v]

    def test_no_index_when_id_none(self, audit_plugin):
        v = GuardianVerdict(risk="harm", label=GuardianScore.NO, raw_output="ok", hook_stage=HookStage.POST)
        audit_plugin._record_verdicts([v], generation_id=None)
        assert v in audit_plugin.all_verdicts
        assert audit_plugin.verdicts_by_generation_id == {}


class TestConcurrency:
    """mellea 0.7 #1175 fires hooks concurrently — record ops must be atomic."""

    def test_parallel_record_verdicts_preserves_all_entries(self, audit_plugin):
        threads = []
        n_threads = 20
        per_thread = 50

        def worker(offset: int):
            for i in range(per_thread):
                gen_id = f"gen-{offset}-{i}"
                v = GuardianVerdict(
                    risk="harm",
                    label=GuardianScore.NO,
                    raw_output=str(i),
                    hook_stage=HookStage.POST,
                )
                audit_plugin._record_verdicts([v], generation_id=gen_id)

        for k in range(n_threads):
            t = threading.Thread(target=worker, args=(k,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert len(audit_plugin.all_verdicts) == n_threads * per_thread
        assert len(audit_plugin.verdicts_by_generation_id) == n_threads * per_thread

    def test_parallel_requirement_id_tracking_is_lock_guarded(self, audit_plugin):
        """Regression for review finding 2.

        ``_requirement_generation_ids`` is now under ``_verdict_lock``.
        Concurrent add() / discard() calls across many ids must not lose any
        add, must not produce spurious survivors after every id has been
        discarded, and must not raise.
        """
        n_threads = 10
        ids_per_thread = 100

        def adder(offset: int):
            for i in range(ids_per_thread):
                gen_id = f"req-{offset}-{i}"
                with audit_plugin._verdict_lock:
                    audit_plugin._requirement_generation_ids.add(gen_id)

        def discarder(offset: int):
            for i in range(ids_per_thread):
                gen_id = f"req-{offset}-{i}"
                with audit_plugin._verdict_lock:
                    audit_plugin._requirement_generation_ids.discard(gen_id)

        add_threads = [
            threading.Thread(target=adder, args=(k,)) for k in range(n_threads)
        ]
        for t in add_threads:
            t.start()
        for t in add_threads:
            t.join()
        assert len(audit_plugin._requirement_generation_ids) == n_threads * ids_per_thread

        discard_threads = [
            threading.Thread(target=discarder, args=(k,)) for k in range(n_threads)
        ]
        for t in discard_threads:
            t.start()
        for t in discard_threads:
            t.join()
        assert audit_plugin._requirement_generation_ids == set()


class TestNewHookCoverage:
    """Every 0.7-added hook type has a subscribed handler on both plugins."""

    def test_audit_plugin_declares_generation_error_hook(self):
        assert hasattr(GuardianAuditPlugin, "check_error")

    def test_audit_plugin_declares_batch_hooks(self):
        assert hasattr(GuardianAuditPlugin, "check_batch_input")
        assert hasattr(GuardianAuditPlugin, "check_batch_output")
        assert hasattr(GuardianAuditPlugin, "check_batch_error")

    def test_enforce_plugin_declares_generation_error_hook(self):
        assert hasattr(GuardianEnforcePlugin, "enforce_error")

    def test_enforce_plugin_declares_batch_hooks(self):
        assert hasattr(GuardianEnforcePlugin, "enforce_batch_input")
        assert hasattr(GuardianEnforcePlugin, "enforce_batch_output")
        assert hasattr(GuardianEnforcePlugin, "enforce_batch_error")

    @pytest.mark.asyncio
    async def test_generation_error_records_error_verdicts(self, audit_plugin):
        payload = SimpleNamespace(
            generation_id="gen-e", error=RuntimeError("boom")
        )
        await audit_plugin.check_error(payload, ctx=None)
        errors = [
            v
            for v in audit_plugin.all_verdicts
            if v.label == GuardianScore.ERROR
        ]
        assert len(errors) == len(audit_plugin.risks)
        assert audit_plugin.verdicts_by_generation_id.get("gen-e"), (
            "generation_error should be indexed by generation_id"
        )
