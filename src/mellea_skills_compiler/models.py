import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Union

from mellea_skills_compiler.enums import CoverageLevel, GovernanceTaxonomy, GuardianMode
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


@dataclass
class NexusRisk:
    """A risk identified by AI Atlas Nexus for this use case.

    Risks fall into two tiers based on their Nexus ``tag`` field:
      - **Native** (``is_native=True``): Guardian has a calibrated assessment
        path for this risk. ``guardian_prompt`` is the bare tag (e.g. "harm",
        "jailbreak", "social_bias").
      - **Custom** (``is_native=False``): No built-in Guardian dimension.
        ``guardian_prompt`` is the description text, sent as
        custom criteria.
    """

    name: str
    description: str
    guardian_prompt: str  # tag (native) or description (custom)
    source: str
    is_native: bool = False  # True when Nexus risk has a tag → calibrated Guardian path
    taxonomy: str = GovernanceTaxonomy.IBM_GRANITE_GUARDIAN


@dataclass
class GovernanceAction:
    """A governance action/mitigation from NIST, Credo UCF, or other taxonomy."""

    id: str
    name: str
    description: str
    source: str  # e.g. "nist-ai-rmf", "credo-ucf"
    category: str = ""  # e.g. "Govern", "Map", "Measure", "Manage"
    via_risk: str = ""  # the risk that linked to this action
    categorized_as: str | list[str] = ""


@dataclass
class PolicyManifest:
    """Policy manifest linking a use case to Guardian checks + governance guidance."""

    use_case: str
    taxonomy: Union[
        str, List[str]
    ]  # risk taxonomy used for runtime checks (e.g. "ibm-granite-guardian")
    risks: list[NexusRisk]
    additional_risks: list[NexusRisk]
    governance_actions: list[GovernanceAction] = field(default_factory=list)
    governance_taxonomies: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    model: str = field(default_factory=str)

    @property
    def risk_prompts(self) -> list[str]:
        """List of Guardian prompts for each identified risk."""
        return [r.guardian_prompt for r in self.risks]

    @property
    def risk_names(self) -> list[str]:
        """List of Guardian risk names for each identified risk."""
        return [r.name for r in self.risks]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | None = None) -> str:
        data = json.dumps(self.to_dict(), indent=2)
        if path:
            with open(path, "w") as f:
                f.write(data)
        return data

    @classmethod
    def from_json(cls, path: str) -> "PolicyManifest":
        """Load a PolicyManifest from a JSON file produced by to_json()."""
        with open(path) as f:
            data = json.load(f)
        risks = [NexusRisk(**r) for r in data.get("risks", [])]
        additional_risks = [NexusRisk(**r) for r in data.get("additional_risks", [])]
        governance_actions = [
            GovernanceAction(**a) for a in data.get("governance_actions", [])
        ]
        return cls(
            use_case=data.get("use_case", ""),
            taxonomy=data.get("taxonomy", GovernanceTaxonomy.IBM_GRANITE_GUARDIAN),
            risks=risks,
            additional_risks=additional_risks,
            governance_actions=governance_actions,
            governance_taxonomies=data.get("governance_taxonomies", []),
            generated_at=data.get("generated_at", ""),
            model=data.get("model", ""),
        )


@dataclass
class RequirementClassification:
    action: GovernanceAction
    coverage: CoverageLevel
    matched_controls: list[str] = field(default_factory=list)


@dataclass
class ComplianceSummary:
    classifications: list[RequirementClassification]

    @property
    def automated(self) -> list[RequirementClassification]:
        return [
            c for c in self.classifications if c.coverage == CoverageLevel.AUTOMATED
        ]

    @property
    def partial(self) -> list[RequirementClassification]:
        return [c for c in self.classifications if c.coverage == CoverageLevel.PARTIAL]

    @property
    def manual(self) -> list[RequirementClassification]:
        return [c for c in self.classifications if c.coverage == CoverageLevel.MANUAL]

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(cl.coverage.value for cl in self.classifications)
        return {
            "AUTOMATED": c.get("AUTOMATED", 0),
            "PARTIAL": c.get("PARTIAL", 0),
            "MANUAL": c.get("MANUAL", 0),
        }


@dataclass
class GuardianVerdict:
    """Result of a single Guardian risk check."""

    risk: str
    label: str  # "Yes" (risk detected), "No" (safe), "Failed", "Error"
    raw_output: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class RunResult:
    guardian_mode: GuardianMode
    guardian_verdict: Dict[str, List[GuardianVerdict]]
    fixture_summary: Dict[str, Any]
    audit_summary: Dict[str, Any]
    guardian_audit_dir: Optional[str] = None

    def dump(self):
        return asdict(self)
