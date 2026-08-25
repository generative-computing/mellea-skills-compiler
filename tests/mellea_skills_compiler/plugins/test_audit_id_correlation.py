"""Audit-trail plugin must correlate Guardian verdicts by generation_id.

The pre-0.7 code sliced the tail of ``guardian.all_verdicts`` positionally,
which is race-prone under mellea 0.7 parallel sampling (PR #1175). The
fix indexes verdicts by generation_id inside the Guardian plugin and
looks them up by id in the audit plugin.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from mellea_skills_compiler.enums import GovernanceTaxonomy, GuardianScore, HookStage
from mellea_skills_compiler.models import GuardianVerdict, NexusRisk
from mellea_skills_compiler.plugins.audit import AuditTrailPlugin
from mellea_skills_compiler.plugins.guardian import GuardianAuditPlugin


@pytest.fixture
def audit_setup(tmp_path: Path):
    risks = [
        NexusRisk(
            name="harm",
            description="",
            guardian_prompt="harm",
            source="test",
            is_native=True,
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
        )
    ]
    gp = GuardianAuditPlugin(risks=risks)
    ap = AuditTrailPlugin(log_path=tmp_path / "audit.jsonl", guardian_plugin=gp)
    return gp, ap


def test_lookup_uses_id_map_when_generation_id_present(audit_setup):
    guardian_plugin, audit_plugin = audit_setup
    v_target = GuardianVerdict(risk="harm", label=GuardianScore.YES, raw_output="", hook_stage=HookStage.POST)
    v_other = GuardianVerdict(risk="harm", label=GuardianScore.NO, raw_output="", hook_stage=HookStage.POST)
    guardian_plugin._record_verdicts([v_target], generation_id="gen-target")
    guardian_plugin._record_verdicts([v_other], generation_id="gen-other")

    hit = audit_plugin._lookup_verdicts_by_generation_id("gen-target")
    assert hit == [v_target]


def test_lookup_falls_back_to_positional_when_id_missing(audit_setup):
    guardian_plugin, audit_plugin = audit_setup
    v = GuardianVerdict(risk="harm", label=GuardianScore.NO, raw_output="", hook_stage=HookStage.POST)
    guardian_plugin._record_verdicts([v], generation_id=None)
    result = audit_plugin._lookup_verdicts_by_generation_id(None)
    assert result == [v]


def test_id_map_and_positional_lookup_return_distinguishable_results(audit_setup):
    """Mixed-concurrent-verdicts case — the motivating race condition.

    Recording under three distinct ids and then asking for id ``gen-b``
    must return exactly that generation's verdicts, not the trailing
    ``len(risks)`` slice which under this arrangement would pick up
    ``gen-c``'s.
    """
    guardian_plugin, audit_plugin = audit_setup
    v_a = GuardianVerdict(risk="harm", label=GuardianScore.YES, raw_output="a", hook_stage=HookStage.POST)
    v_b = GuardianVerdict(risk="harm", label=GuardianScore.NO, raw_output="b", hook_stage=HookStage.POST)
    v_c = GuardianVerdict(risk="harm", label=GuardianScore.FAILED, raw_output="c", hook_stage=HookStage.POST)
    guardian_plugin._record_verdicts([v_a], generation_id="gen-a")
    guardian_plugin._record_verdicts([v_b], generation_id="gen-b")
    guardian_plugin._record_verdicts([v_c], generation_id="gen-c")

    # id-map lookup returns the target's verdict, regardless of insertion order
    assert audit_plugin._lookup_verdicts_by_generation_id("gen-b") == [v_b]
    # positional fallback returns the trailing slice — proving the two paths
    # are distinguishable and that id-keyed lookup is the correct fix.
    positional = audit_plugin._lookup_verdicts_by_generation_id(None)
    assert positional == [v_c], (
        "positional-fallback should return the last-recorded verdict; if this "
        "test fails, the fallback stopped being distinguishable from the id-map"
    )
