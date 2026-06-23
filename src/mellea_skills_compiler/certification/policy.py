"""AI Atlas Nexus policy generation for Mellea Skills Compiler."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import List, Optional

from mellea_skills_compiler.enums import (
    GovernanceTaxonomy,
    InferenceEngineType,
    NexusRiskSource,
)
from mellea_skills_compiler.inference import InferenceService
from mellea_skills_compiler.models import GovernanceAction, NexusRisk, PolicyManifest
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


def _get_fail_safe_risks():
    return [
        NexusRisk(
            name=risk,
            description="",
            guardian_prompt=risk,
            source=NexusRiskSource.DEFAULT_FALLBACK,
            is_native=True,
            taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
        )
        for risk in [
            "harm",
            "social_bias",
            "jailbreak",
        ]
    ]


def generate_policy_manifest(
    use_case: str,
    nexus,
    model: Optional[str] = None,
    inference_engine: InferenceEngineType = InferenceEngineType.OLLAMA,
    governance_taxonomies: Optional[List[str]] = None,
) -> PolicyManifest:
    """Identify applicable risks and governance actions to produce a multi-taxonomy policy manifest.

    Args:
        use_case (str): Natural language description of the agent's purpose.
        nexus (AIAtlasNexus): AI Atlas Nexus instance.
        model (Optional[str], optional): Model to use for Risk and Action Identification. The `inference_engine` param must support the model. If set to None, the default model for the inference engine will be used.
        inference_engine (InferenceEngineType, optional): Service to use for LLM inference. Defaults to InferenceEngineType.OLLAMA.
        governance_taxonomies: List of taxonomy IDs for governance actions.
    Returns:
        PolicyManifest with Guardian risks and governance actions.
    """

    if not governance_taxonomies:
        governance_taxonomies = GovernanceTaxonomy.list()

    # Create Inference engine instance
    risk_inference_engine = InferenceService(inference_engine).risk(
        model, parameters={"temperature": 0}
    )

    risk_lists = nexus.identify_risks_and_actions_from_usecases(
        [use_case],
        risk_inference_engine,
        taxonomy=governance_taxonomies,
        zero_shot_only=True,
    )

    identified_risks = risk_lists.get("risks", [])
    LOGGER.info(f"AI Atlas Nexus risks: {len(identified_risks)}")

    risks = []
    additional_risks = []

    for risk in identified_risks:
        description = guardian_prompt = getattr(risk, "description", "").strip()

        # sort the risks, granite guardian and other
        if risk.isDefinedByTaxonomy == GovernanceTaxonomy.IBM_GRANITE_GUARDIAN:
            guardian_prompt = risk.tag if risk.tag else guardian_prompt
            is_native = True if risk.tag else False
            risks.append(
                NexusRisk(
                    name=risk.name,
                    description=description,
                    guardian_prompt=guardian_prompt,
                    source=NexusRiskSource.AI_ATLAS_NEXUS,
                    is_native=is_native,
                    taxonomy=risk.isDefinedByTaxonomy,
                )
            )
        else:
            additional_risks.append(
                NexusRisk(
                    name=risk.name,
                    description=description,
                    guardian_prompt=guardian_prompt,
                    source=NexusRiskSource.AI_ATLAS_NEXUS,
                    is_native=False,
                    taxonomy=risk.isDefinedByTaxonomy,
                )
            )

    if not risks:
        LOGGER.warning(
            "AI Atlas Nexus returned no Granite Guardian risks for this use case. "
            "Falling back to default native risks: ['harm', 'social_bias', 'jailbreak']. "
            "These are generic fail-safe defaults, NOT derived from use-case analysis. "
        )
        risks = _get_fail_safe_risks()

    LOGGER.info("Guardian risks: %d", len(risks))
    for risk in risks:
        LOGGER.info(
            f"  [Guardian] {risk.name} ({"native" if risk.is_native else "custom"}) → {risk.guardian_prompt[:60]}"
        )

    # -- 2. Use the actions which are directly linked the risks
    identified_risks_governance_actions = risk_lists.get("mixed_control_items", [])
    governance_actions: list[GovernanceAction] = []
    for governance_item in identified_risks_governance_actions:
        governance_actions.append(
            GovernanceAction(
                id=governance_item.id,
                name=governance_item.name or governance_item.id,
                description=governance_item.description or "",
                source=governance_item.isDefinedByTaxonomy,
                category="",
                via_risk="",
                categorized_as=governance_item.isCategorizedAs,
            )
        )
    LOGGER.info("Governance actions: %d", len(governance_actions))

    return PolicyManifest(
        use_case=use_case,
        taxonomy=governance_taxonomies,
        risks=risks,
        additional_risks=additional_risks,
        governance_actions=governance_actions,
        governance_taxonomies=governance_taxonomies,
        model=risk_inference_engine.model_name_or_path,
    )


def generate_policy_markdown(manifest: PolicyManifest) -> str:
    """Generate a human-readable .md policy document from a manifest.

    Includes:
      - Guardian runtime risk checks (what the hooks monitor)
      - NIST AI RMF governance actions (organisational requirements)
      - Credo UCF controls (specific mitigation measures)
      - Guardrail configuration table
      - Audit trail specification
    """
    all_taxonomies = manifest.governance_taxonomies
    lines = [
        f"# Policy: {manifest.use_case}",
        "",
        f"**Generated**: {manifest.generated_at}  ",
        f"**Risk identification model**: {manifest.model}  ",
        f"**Taxonomies**: {', '.join(all_taxonomies)}",
    ]
    lines.extend(["", "---", ""])

    # ── Section 1: Guardian runtime checks ──────────────────────────
    lines.extend(
        [
            "## 1. Runtime Risk Checks (Granite Guardian)",
            "",
            "The following risks are checked at runtime on every LLM generation "
            "via the Granite Guardian 3.3-8B model. Risk descriptions are sourced "
            "from the IBM Granite Guardian taxonomy in AI Atlas Nexus and used as "
            "Guardian system prompts.",
            "",
        ]
    )

    for i, risk in enumerate(manifest.risks, 1):
        tier_label = "Native dimension" if risk.is_native else "Custom criteria"
        lines.extend(
            [
                f"### 1.{i} {risk.name}",
                "",
                f"**Guardian tier**: {tier_label}  ",
                f"**Guardian prompt**: `{risk.guardian_prompt}`",
                "",
                f"{risk.description}",
                "",
            ]
        )

    # ── Section 2: Governance actions (per taxonomy) ────────────────
    if manifest.governance_actions:
        # Group actions by source taxonomy
        by_source: dict[str, list[GovernanceAction]] = defaultdict(list)
        for action in manifest.governance_actions:
            by_source[action.source].append(action)

        section_num = 2
        for source, actions in by_source.items():
            lines.extend(
                [
                    "---",
                    "",
                    f"## {section_num}. Governance Requirements ({source})",
                    "",
                    f"**{len(actions)}** governance actions collected from "
                    f"the **{source}** taxonomy.",
                    "",
                ]
            )

            # Sub-group by category if categories exist (e.g. NIST Govern/Map/Measure/Manage)
            by_cat: dict[str, list[GovernanceAction]] = defaultdict(list)
            for action in actions:
                by_cat[action.category or "General"].append(action)

            cat_order = ["Govern", "Map", "Measure", "Manage", "General", "Other"]
            for cat in cat_order:
                cat_actions = by_cat.get(cat, [])
                if not cat_actions:
                    continue
                if cat != "General" or len(by_cat) > 1:
                    lines.extend([f"### {section_num}.{cat[0]}. {cat}", ""])
                for action in cat_actions:
                    desc = action.description
                    if len(desc) > 300:
                        desc = desc[:297] + "..."
                    lines.extend(
                        [
                            f"- **[{action.id}]** {desc}",
                            "",
                        ]
                    )

            section_num += 1

    # ── Guardrail configuration ──────────────────────────────────────
    # section_num is already set from the governance loop (or 2 if no governance)
    if not manifest.governance_actions:
        section_num = 2
    lines.extend(
        [
            "---",
            "",
            f"## {section_num}. Guardrail Configuration",
            "",
            "| Risk | Tier | Guardian Prompt | Hook | Mode | Priority |",
            "|------|------|----------------|------|------|----------|",
        ]
    )
    for risk in manifest.risks:
        tier = "Native" if risk.is_native else "Custom"
        lines.append(
            f"| {risk.name} | {tier} | `{risk.guardian_prompt}` "
            f"| `generation_post_call` | AUDIT | 40 |"
        )

    # ── Audit trail ──────────────────────────────────────────────────
    section_num += 1
    lines.extend(
        [
            "",
            f"## {section_num}. Audit Trail",
            "",
            "All generation events are logged to `audit_trail.jsonl` with:",
            "- Guardian verdicts per risk (from Section 1)",
            "- Component lifecycle events (pre-execute, post-success, post-error)",
            "- Validation outcomes",
            "- Policy manifest ID for traceability back to this document",
            "",
            "The governance guidance sections are organisational requirements — "
            "they inform how the agent should be deployed, monitored, and "
            "governed, complementing the automated runtime checks in Section 1.",
        ]
    )

    return "\n".join(lines)


def load_policy_manifest(manifest_path: Path) -> PolicyManifest:
    """Search for policy_manifest.json in standard locations.

    Checks the skill root first (portable), then the audit directory.
    """
    if manifest_path.is_file():
        try:
            return PolicyManifest.from_json(str(manifest_path))
        except Exception as e:
            raise Exception(
                f"Failed to load policy manifest from {manifest_path}: {str(e)}",
            )

    raise Exception(f"Policy manifest not available at {manifest_path}.")
