#!/usr/bin/env python3
"""Mellea Skills Compiler — Ingest an OpenClaw SKILL.md and certify it.

Pipeline:
  1. Parse SKILL.md (YAML frontmatter + markdown body)
  2. Classify tool sensitivity tier (lookup table, no regex)
  3. Compose use-case description for Nexus
  4. Nexus risk identification → policy manifest
  5. Compliance classification
  6. Certification report
"""

from pathlib import Path
from typing import Optional

from mellea_skills_compiler.certification import policy, skill_to_use_case
from mellea_skills_compiler.certification.classification import (
    classify_governance_requirements,
    classify_skill_sensitivity,
)
from mellea_skills_compiler.certification.data import get_data_path
from mellea_skills_compiler.certification.report import generate_certification_report
from mellea_skills_compiler.enums import InferenceEngineType
from mellea_skills_compiler.toolkit.file_utils import parse_spec_file
from mellea_skills_compiler.toolkit.logging import configure_logger


log = configure_logger()


def ingest_one(
    spec_path: Path,
    dry_run: bool = False,
    model: Optional[str] = None,
    inference_engine: InferenceEngineType = InferenceEngineType.OLLAMA,
):
    """Risk Analysis and Policy Generation Pipeline for Mellea skill

    Args:
        skill_name (str): Mellea Skill spec path.
        dry_run (bool, optional): Preview without making LLM calls. Defaults to False.
        model (Optional[str], optional): Model to use for Risk and Action Identification. The `inference_engine` param must support the model. If set to None, the default model for the inference engine will be used.
        inference_engine (InferenceEngineType, optional): Service to use for LLM inference. Defaults to InferenceEngineType.OLLAMA.
    """

    # Verify that spec file ends in a .md extension
    if spec_path.suffix != ".md":
        raise ValueError(
            f"invalid spec file - {spec_path}. Only markdown (.md) file is supported."
        )

    # Verify the spec file exists
    if spec_path.exists():
        # Verify that given path is not a directory
        if spec_path.is_dir():
            raise ValueError(
                "The specified path is a directory. Please note that the compile command only accepts a skill spec file in .md format."
            )
    else:
        raise FileNotFoundError(f"Skill spec file not found: {spec_path}")

    log.info("=== MelleaSkills — SKILL.md Ingestion ===")
    log.info("")

    # ── Step 1: Parse ───────────────────────────────────────────────
    log.info("Step 1: Parsing %s...", spec_path.name)
    parsed = parse_spec_file(spec_path)
    fm = parsed["frontmatter"]
    log.info("  Name: %s", fm.get("name", "unknown"))
    log.info("  Description: %.100s", fm.get("description", ""))
    log.info("  Tools: %s", fm.get("allowed-tools", []))
    log.info("")

    # ── Step 2: Sensitivity classification ──────────────────────────
    log.info("Step 2: Tool sensitivity classification...")
    sensitivity = classify_skill_sensitivity(
        fm.get("allowed-tools", []), parsed["body"]
    )
    log.info("  Tier: %s", sensitivity["tier_display"])
    log.info("  Operations: %s", sensitivity["operations"])
    if sensitivity["capabilities"]:
        log.info("  Capabilities: %s", sensitivity["capabilities"])
    log.info("")

    # ── Step 3: Compose use-case description ────────────────────────
    use_case = skill_to_use_case(parsed, sensitivity)
    log.info("Step 3: Use-case description:")
    log.info("  %s", use_case)
    log.info("")

    if dry_run:
        log.info("=== Dry-run complete ===")
        return

    # load and create ai atlas nexus instance
    from ai_atlas_nexus.library import AIAtlasNexus

    nexus_data_path = get_data_path()
    nexus = AIAtlasNexus(base_dir=nexus_data_path)

    # ── Step 4: Nexus risk identification ───────────────────────────
    log.info("Step 4: Identifying risks via AI Atlas Nexus...")

    # Certification artifacts go into the skill's audit/ directory
    audit_dir = spec_path.parent / "audit"
    audit_dir.mkdir(exist_ok=True)

    # Genereate policy manifest
    manifest = policy.generate_policy_manifest(
        use_case, nexus, model, inference_engine
    )
    manifest_path = audit_dir / "policy_manifest.json"
    manifest.to_json(manifest_path)

    # Generate policy markdown
    policy_md = policy.generate_policy_markdown(manifest)
    policy_path = audit_dir / "POLICY.md"
    policy_path.write_text(policy_md)

    log.info("  Guardian risks: %d", len(manifest.risks))
    for r in manifest.risks:
        tier = "native" if r.is_native else "custom"
        log.info("    - %s (%s)", r.name, tier)
    log.info("  Governance actions: %d", len(manifest.governance_actions))
    log.info("Policy manifest: %s", manifest_path)
    log.info("Policy document: %s", policy_path)

    # ── Step 5: Compliance classification ───────────────────────────
    log.info("Step 5: Compliance classification...")
    compliance = classify_governance_requirements(manifest, nexus)
    counts = compliance.counts
    log.info(
        "  AUTOMATED=%d  PARTIAL=%d  MANUAL=%d  (total=%d)",
        counts["AUTOMATED"],
        counts["PARTIAL"],
        counts["MANUAL"],
        sum(counts.values()),
    )
    log.info("")

    # ── Step 6: Certification report ────────────────────────────────
    log.info("Step 6: Generating certification report...")
    report = generate_certification_report(
        manifest,
        compliance,
        audit_trail=[],
        audit_path="(no runtime audit — static analysis only)",
    )
    report_path = audit_dir / "CERTIFICATION.md"
    report_path.write_text(report)
    log.info("  Artifact: %s", report_path.name)
    log.info("")

    # ── Summary ─────────────────────────────────────────────────────
    skill_name = fm.get("name", "unknown")
    log.info("=== Summary: %s ===", skill_name)
    log.info(
        "  Sensitivity: %s | Operations: %s",
        sensitivity["tier_display"],
        sensitivity["operations"],
    )
    log.info(
        "  Guardian risks: %d | Governance actions: %d",
        len(manifest.risks),
        len(manifest.governance_actions),
    )
    log.info(
        "  Compliance: AUTOMATED=%d PARTIAL=%d MANUAL=%d",
        counts["AUTOMATED"],
        counts["PARTIAL"],
        counts["MANUAL"],
    )
