"""Unit tests for mellea_skills_compiler.certification.compliance module."""

import json
import os
import tempfile
from pathlib import Path

from mellea_skills_compiler.certification.classification import (
    classify_governance_requirements,
)
from mellea_skills_compiler.certification.data import get_data_path
from mellea_skills_compiler.certification.report import (
    generate_certification_report,
    load_audit_trail,
)
from mellea_skills_compiler.enums import GovernanceTaxonomy
from mellea_skills_compiler.models import (
    ComplianceSummary,
    CoverageLevel,
    GovernanceAction,
    NexusRisk,
    PolicyManifest,
    RequirementClassification,
)


class TestCoverageLevel:
    """Test cases for CoverageLevel enum."""

    def test_coverage_levels(self):
        """Test that coverage levels are defined correctly."""
        assert CoverageLevel.AUTOMATED.value == "AUTOMATED"
        assert CoverageLevel.PARTIAL.value == "PARTIAL"
        assert CoverageLevel.MANUAL.value == "MANUAL"


class TestRequirementClassification:
    """Test cases for RequirementClassification dataclass."""

    def test_create_classification(self):
        """Test creating a requirement classification."""
        action = GovernanceAction(
            id="GV-1",
            name="Test",
            description="Test action",
            source="nist-ai-rmf",
        )

        classification = RequirementClassification(
            action=action,
            coverage=CoverageLevel.AUTOMATED,
            matched_controls=["pc-content-safety", "pc-generation-audit"],
        )

        assert classification.action.id == "GV-1"
        assert classification.coverage == CoverageLevel.AUTOMATED
        assert len(classification.matched_controls) == 2


class TestComplianceSummary:
    """Test cases for ComplianceSummary dataclass."""

    def test_automated_property(self):
        """Test filtering automated classifications."""
        action1 = GovernanceAction("A-1", "Test1", "Desc1", "test")
        action2 = GovernanceAction("A-2", "Test2", "Desc2", "test")
        action3 = GovernanceAction("A-3", "Test3", "Desc3", "test")

        classifications = [
            RequirementClassification(action1, CoverageLevel.AUTOMATED, "Automated"),
            RequirementClassification(action2, CoverageLevel.PARTIAL, "Partial"),
            RequirementClassification(action3, CoverageLevel.AUTOMATED, "Automated"),
        ]

        summary = ComplianceSummary(classifications)
        automated = summary.automated

        assert len(automated) == 2
        assert all(c.coverage == CoverageLevel.AUTOMATED for c in automated)

    def test_partial_property(self):
        """Test filtering partial classifications."""
        action1 = GovernanceAction("A-1", "Test1", "Desc1", "test")
        action2 = GovernanceAction("A-2", "Test2", "Desc2", "test")

        classifications = [
            RequirementClassification(action1, CoverageLevel.AUTOMATED, "Automated"),
            RequirementClassification(action2, CoverageLevel.PARTIAL, "Partial"),
        ]

        summary = ComplianceSummary(classifications)
        partial = summary.partial

        assert len(partial) == 1
        assert partial[0].coverage == CoverageLevel.PARTIAL

    def test_manual_property(self):
        """Test filtering manual classifications."""
        action1 = GovernanceAction("A-1", "Test1", "Desc1", "test")
        action2 = GovernanceAction("A-2", "Test2", "Desc2", "test")

        classifications = [
            RequirementClassification(action1, CoverageLevel.MANUAL, "Manual"),
            RequirementClassification(action2, CoverageLevel.PARTIAL, "Partial"),
        ]

        summary = ComplianceSummary(classifications)
        manual = summary.manual

        assert len(manual) == 1
        assert manual[0].coverage == CoverageLevel.MANUAL

    def test_counts_property(self):
        """Test coverage counts."""
        action1 = GovernanceAction("A-1", "Test1", "Desc1", "test")
        action2 = GovernanceAction("A-2", "Test2", "Desc2", "test")
        action3 = GovernanceAction("A-3", "Test3", "Desc3", "test")
        action4 = GovernanceAction("A-4", "Test4", "Desc4", "test")

        classifications = [
            RequirementClassification(action1, CoverageLevel.AUTOMATED, "Auto"),
            RequirementClassification(action2, CoverageLevel.AUTOMATED, "Auto"),
            RequirementClassification(action3, CoverageLevel.PARTIAL, "Partial"),
            RequirementClassification(action4, CoverageLevel.MANUAL, "Manual"),
        ]

        summary = ComplianceSummary(classifications)
        counts = summary.counts

        assert counts["AUTOMATED"] == 2
        assert counts["PARTIAL"] == 1
        assert counts["MANUAL"] == 1


class TestLoadAuditTrail:
    """Test cases for load_audit_trail function."""

    def test_load_valid_audit_trail(self):
        """Test loading a valid JSONL audit trail."""
        entries = [
            {"hook": "generation_pre_call", "timestamp": "2024-01-01T00:00:00Z"},
            {"hook": "generation_post_call", "timestamp": "2024-01-01T00:00:01Z"},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            path = f.name

        try:
            loaded = load_audit_trail(path)

            assert len(loaded) == 2
            assert loaded[0]["hook"] == "generation_pre_call"
            assert loaded[1]["hook"] == "generation_post_call"
        finally:
            Path(path).unlink()

    def test_load_nonexistent_audit_trail(self):
        """Test loading from nonexistent file returns empty list."""
        entries = load_audit_trail("/nonexistent/path/audit.jsonl")
        assert entries == []

    def test_load_empty_lines_ignored(self):
        """Test that empty lines in JSONL are ignored."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"hook": "test1"}\n')
            f.write("\n")
            f.write('{"hook": "test2"}\n')
            f.write("  \n")
            path = f.name

        try:
            loaded = load_audit_trail(path)
            assert len(loaded) == 2
        finally:
            Path(path).unlink()


class TestClassifyRequirements:
    """Test cases for classify_requirements function."""

    @classmethod
    def setup_class(cls):
        # load atlas once
        from ai_atlas_nexus.library import AIAtlasNexus

        nexus_data_path = get_data_path()
        nexus = AIAtlasNexus(base_dir=nexus_data_path)
        cls.nexus = nexus

    def test_classify_with_automated_coverage(self):
        """Test classification with automated coverage (2+ implemented controls)."""

        action = GovernanceAction(
            id="GV-1",
            name="Test Action",
            description="Test",
            source="nist-ai-rmf",
        )

        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[],
            additional_risks=[],
            governance_actions=[action],
        )

        compliance = classify_governance_requirements(manifest, self.nexus)

        assert len(compliance.classifications) == 1
        assert compliance.classifications[0].coverage == CoverageLevel.MANUAL
        assert len(compliance.manual) == 1

    def test_classify_with_manual_coverage(self):
        """Test classification with manual coverage (no implemented controls)."""

        action = GovernanceAction(
            id="GV-1",
            name="Test Action",
            description="Test",
            source="nist-ai-rmf",
        )

        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[],
            additional_risks=[],
            governance_actions=[action],
        )

        compliance = classify_governance_requirements(manifest, self.nexus)

        assert compliance.classifications[0].coverage == CoverageLevel.MANUAL
        assert len(compliance.manual) == 1

    def test_classify_unmapped_action(self):
        """Test classification of action with no mapping (defaults to MANUAL)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("{}")  # Empty mappings
            mappings_path = f.name

        try:
            action = GovernanceAction(
                id="UNMAPPED-1",
                name="Unmapped Action",
                description="Test",
                source="test",
            )

            manifest = PolicyManifest(
                use_case="Test",
                taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
                risks=[],
                additional_risks=[],
                governance_actions=[action],
            )

            compliance = classify_governance_requirements(manifest, self.nexus)

            assert compliance.classifications[0].coverage == CoverageLevel.MANUAL

        finally:
            Path(mappings_path).unlink()


class TestGenerateCertificationReport:
    """Test cases for generate_certification_report function."""

    def test_generate_basic_report(self):
        """Test generating a basic certification report."""
        action = GovernanceAction(
            id="GV-1",
            name="Test Action",
            description="Test description",
            source="nist-ai-rmf",
            category="Govern",
        )

        classification = RequirementClassification(
            action=action,
            coverage=CoverageLevel.AUTOMATED,
            matched_controls=["pc-content-safety"],
        )

        manifest = PolicyManifest(
            use_case="Test Use Case",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[
                NexusRisk(
                    name="Risk1",
                    description="Desc1",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt1",
                ),
                NexusRisk(
                    name="Risk2",
                    description="Desc2",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt2",
                ),
                NexusRisk(
                    name="Custom Risk",
                    description="A custom risk description",
                    guardian_prompt="A custom risk description Custom concern",
                    source="ai-atlas-nexus",
                    is_native=False,
                ),
            ],
            additional_risks=[],
            governance_actions=[action],
        )

        compliance = ComplianceSummary(classifications=[classification])
        audit_trail = []

        report = generate_certification_report(
            manifest, compliance, audit_trail, audit_path="test.jsonl"
        )

        assert "# Certification Report" in report
        assert "Test Use Case" in report
        assert "AUTOMATED" in report
        assert "GV-1" in report

    def test_report_includes_guardian_section(self):
        """Test that report includes Guardian runtime checks section."""
        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[
                NexusRisk(
                    name="Risk1",
                    description="Desc1",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt1",
                ),
                NexusRisk(
                    name="Risk2",
                    description="Desc2",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt2",
                ),
                NexusRisk(
                    name="Custom Risk",
                    description="A custom risk description",
                    source="ai-atlas-nexus",
                    guardian_prompt="A custom risk description Custom concern",
                    is_native=False,
                ),
            ],
            additional_risks=[],
        )

        compliance = ComplianceSummary(classifications=[])
        audit_trail = []

        report = generate_certification_report(manifest, compliance, audit_trail)

        assert "Guardian Runtime Checks" in report

    def test_report_includes_audit_summary(self):
        """Test that report includes audit trail summary."""
        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[
                NexusRisk(
                    name="Risk1",
                    description="Desc1",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt1",
                ),
                NexusRisk(
                    name="Risk2",
                    description="Desc2",
                    source="ai-atlas-nexus",
                    guardian_prompt="prompt2",
                ),
                NexusRisk(
                    name="Custom Risk",
                    description="A custom risk description",
                    source="ai-atlas-nexus",
                    guardian_prompt="A custom risk description Custom concern",
                    is_native=False,
                ),
            ],
            additional_risks=[],
        )

        compliance = ComplianceSummary(classifications=[])
        audit_trail = [
            {"hook": "generation_pre_call", "timestamp": "2024-01-01T00:00:00Z"},
        ]

        report = generate_certification_report(manifest, compliance, audit_trail)

        assert "Audit Trail Summary" in report
        assert "1 total audit events recorded" in report
