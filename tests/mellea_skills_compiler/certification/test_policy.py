"""Unit tests for mellea_skills_compiler.certification.policy module."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from mellea_skills_compiler.enums import GovernanceTaxonomy
from mellea_skills_compiler.models import GovernanceAction, NexusRisk, PolicyManifest


class TestNexusRisk:
    """Test cases for NexusRisk dataclass."""

    def test_create_native_risk(self):
        """Test creating a native risk with a tag."""
        risk = NexusRisk(
            name="Jailbreak",
            description="Attempts to bypass safety guidelines",
            guardian_prompt="jailbreak",
            source="ai-atlas-nexus",
            is_native=True,
        )

        assert risk.name == "Jailbreak"
        assert risk.description == "Attempts to bypass safety guidelines"
        assert risk.guardian_prompt == "jailbreak"
        assert risk.is_native is True
        assert risk.taxonomy == GovernanceTaxonomy.IBM_GRANITE_GUARDIAN

    def test_create_custom_risk(self):
        """Test creating a custom risk without a tag."""
        risk = NexusRisk(
            name="Custom Risk",
            description="A custom risk description",
            source="ai-atlas-nexus",
            guardian_prompt="A custom risk description Custom concern",
            is_native=False,
        )

        assert risk.is_native is False
        assert risk.guardian_prompt == "A custom risk description Custom concern"


class TestGovernanceAction:
    """Test cases for GovernanceAction dataclass."""

    def test_create_nist_action(self):
        """Test creating a NIST AI RMF governance action."""
        action = GovernanceAction(
            id="GV-1.1",
            name="Legal and Regulatory Requirements",
            description="Map and manage AI risks",
            source="nist-ai-rmf",
            category="Govern",
            via_risk="Some risk",
        )

        assert action.id == "GV-1.1"
        assert action.name == "Legal and Regulatory Requirements"
        assert action.source == "nist-ai-rmf"
        assert action.category == "Govern"
        assert action.via_risk == "Some risk"

    def test_create_credo_action(self):
        """Test creating a Credo UCF governance action."""
        action = GovernanceAction(
            id="credo-ctrl-1",
            name="Control measure",
            description="Implement control",
            source="credo-ucf",
        )

        assert action.source == "credo-ucf"
        assert action.category == ""


class TestPolicyManifest:
    """Test cases for PolicyManifest dataclass."""

    def test_create_manifest(self):
        """Test creating a basic policy manifest."""
        risks = [
            NexusRisk(
                name="Test Risk",
                description="Test description",
                guardian_prompt="test",
                source="ai-atlas-nexus",
                is_native=True,
            )
        ]
        actions = [
            GovernanceAction(
                id="GV-1",
                name="Governance",
                description="Govern AI",
                source="nist-ai-rmf",
                category="Govern",
            )
        ]

        manifest = PolicyManifest(
            use_case="Test use case",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=risks,
            additional_risks=[],
            governance_actions=actions,
            governance_taxonomies=["nist-ai-rmf"],
        )

        assert manifest.use_case == "Test use case"
        assert manifest.taxonomy == GovernanceTaxonomy.IBM_GRANITE_GUARDIAN
        assert len(manifest.risks) == 1
        assert len(manifest.governance_actions) == 1

    def test_guardian_risks_property(self):
        """Test guardian_risks property returns guardian prompts."""
        risks = [
            NexusRisk(
                name="Risk1",
                description="Desc1",
                guardian_prompt="prompt1",
                source="ai-atlas-nexus",
                is_native=True,
            ),
            NexusRisk(
                name="Risk2",
                description="Desc2",
                guardian_prompt="prompt2",
                source="ai-atlas-nexus",
                is_native=False,
            ),
        ]

        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=risks,
            additional_risks=[],
        )

        guardian_risks = manifest.risk_prompts
        assert guardian_risks == ["prompt1", "prompt2"]

    def test_risk_names_property(self):
        """Test risk_names property returns risk names."""
        risks = [
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
        ]

        manifest = PolicyManifest(
            use_case="Test",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=risks,
            additional_risks=[],
        )

        assert manifest.to_dict()["taxonomy"] == GovernanceTaxonomy.IBM_GRANITE_GUARDIAN
        assert [risk["name"] for risk in manifest.to_dict()["risks"]] == [
            "Risk1",
            "Risk2",
            "Custom Risk",
        ]

    def test_to_dict(self):
        """Test converting manifest to dictionary."""
        risk = NexusRisk(
            name="TestRisk",
            description="Test",
            source="ai-atlas-nexus",
            guardian_prompt="test",
        )

        manifest = PolicyManifest(
            use_case="Test use case",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[risk],
            additional_risks=[],
        )

        result = manifest.to_dict()

        assert isinstance(result, dict)
        assert result["use_case"] == "Test use case"
        assert result["taxonomy"] == GovernanceTaxonomy.IBM_GRANITE_GUARDIAN
        assert len(result["risks"]) == 1

    def test_to_json_string(self):
        """Test converting manifest to JSON string."""
        risk = NexusRisk(
            name="TestRisk",
            description="Test",
            source="ai-atlas-nexus",
            guardian_prompt="test",
        )

        manifest = PolicyManifest(
            use_case="Test use case",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[risk],
            additional_risks=[],
        )

        json_str = manifest.to_json()

        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["use_case"] == "Test use case"

    def test_to_json_file(self):
        """Test writing manifest to JSON file."""
        risk = NexusRisk(
            name="TestRisk",
            description="Test",
            source="ai-atlas-nexus",
            guardian_prompt="test",
        )

        manifest = PolicyManifest(
            use_case="Test use case",
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            risks=[risk],
            additional_risks=[],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name

        try:
            manifest.to_json(path)

            with open(path) as f:
                data = json.load(f)

            assert data["use_case"] == "Test use case"
            assert len(data["risks"]) == 1
        finally:
            Path(path).unlink()

    def test_from_json(self):
        """Test loading manifest from JSON file."""
        data = {
            "use_case": "Test use case",
            "taxonomy": GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
            "risks": [
                {
                    "name": "TestRisk",
                    "description": "Test description",
                    "guardian_prompt": "test",
                    "source": "ai-atlas-nexus",
                    "is_native": True,
                    "taxonomy": GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
                }
            ],
            "governance_actions": [
                {
                    "id": "GV-1",
                    "name": "Governance",
                    "description": "Test action",
                    "source": "nist-ai-rmf",
                    "category": "Govern",
                    "via_risk": "TestRisk",
                }
            ],
            "governance_taxonomies": ["nist-ai-rmf"],
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "test-model",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            manifest = PolicyManifest.from_json(path)

            assert manifest.use_case == "Test use case"
            assert len(manifest.risks) == 1
            assert manifest.risks[0].name == "TestRisk"
            assert len(manifest.governance_actions) == 1
            assert manifest.governance_actions[0].id == "GV-1"
        finally:
            Path(path).unlink()
