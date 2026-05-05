#!/usr/bin/env python3
"""Mellea Skills Compiler — Full Pipeline: SKILL.md → decomposed pipeline → Guardian → certification.

End-to-end demonstration:
  1. Ingest a SKILL.md → parse, classify sensitivity, compose use-case
  2. Identify risks via AI Atlas Nexus → policy manifest
  3. Configure Guardian hooks from manifest (pre + post generation)
  4. Run test fixtures through the DECOMPOSED pipeline
     → Guardian intercepts every m.instruct() call inside the pipeline
     → Audit trail captures every generation + Guardian verdict
  5. Compliance classification
  6. Certification report with runtime evidence
"""

import json
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

from mellea.plugins import PluginViolationError
from rich.console import Console

from mellea_skills_compiler.certification.classification import (
    classify_governance_requirements,
)
from mellea_skills_compiler.certification.data import get_data_path
from mellea_skills_compiler.certification.nexus_policy import (
    generate_policy_manifest,
    generate_policy_markdown,
    load_policy_manifest,
)
from mellea_skills_compiler.certification.report import (
    generate_certification_report,
    load_audit_trail,
)
from mellea_skills_compiler.enums import InferenceEngineType, SpecFileFormat
from mellea_skills_compiler.guardian import deregister_plugins, register_plugins
from mellea_skills_compiler.toolkit.file_utils import (
    load_fixtures,
    load_skill_pipeline,
    parse_spec_file,
)
from mellea_skills_compiler.toolkit.logging import configure_logger


console = Console(log_time=True)

LOGGER = configure_logger()


def _run_single_fixture(pipeline_fn: Callable, fixture: Dict):
    report = None
    try:
        context = fixture["context"]

        # Unpack dict context as kwargs (Pattern 2 pipelines expect keyword args)
        if isinstance(context, dict):
            report = pipeline_fn(**context)
        else:
            report = pipeline_fn(context)

        LOGGER.info("Pipeline completed successfully.")

        # Log key fields if available
        for field in ["location", "weather_data", "action", "summary"]:
            if hasattr(report, field) and getattr(report, field):
                LOGGER.info("  %s: %s", field, str(getattr(report, field))[:100])

    except PluginViolationError as e:
        print()
        LOGGER.warning("Pipeline BLOCKED by Guardian enforcement: %s", e.reason)
        LOGGER.warning("  The decomposed pipeline was halted because a generation")
        LOGGER.warning("  triggered a Guardian risk detection in ENFORCE mode.")
        print()

    return report


def skill_pipeline(
    pipeline_dir: Path,
    fixture_id: str,
    enforce: bool = False,
    no_guardian: bool = False,
):
    # Verify skill pipeline directory exists
    if pipeline_dir.exists():
        # Verify that given path is a directory
        if not pipeline_dir.is_dir():
            raise ValueError(
                "The specified path is not a directory. Please note that the run command only accepts a compiled skill directory."
            )
    else:
        raise FileNotFoundError(f"Skill pipeline directory not found: {pipeline_dir}")

    # Load skill pipeline
    pipeline_fn = load_skill_pipeline(pipeline_dir)

    # Load fixtures from the pipeline directory
    fixtures = load_fixtures(pipeline_dir)

    # Get the desired fixture
    fixture = None
    for f in fixtures:
        if fixture_id == f["id"]:
            fixture = f
            break
    if fixture is None:
        available = [f["id"] for f in fixtures]
        LOGGER.error("Unknown fixture '%s'. Available: %s", fixture_id, available)
        sys.exit(1)

    # --- Guardian hook registration ---
    guardian_plugin, audit_plugin = None, None
    if no_guardian:
        LOGGER.info("Guardian checks disabled (--no-guardian)")
    else:
        try:
            # Audit directory
            audit_dir = pipeline_dir.parent / "audit"

            if not audit_dir.is_dir():
                raise ValueError(
                    f"The audit directory is not available in {pipeline_dir.parent}"
                )

            manifest = load_policy_manifest(audit_dir)
            guardian_plugin, audit_plugin = register_plugins(
                manifest, audit_dir, enforce
            )
            LOGGER.info("=" * 60)
            LOGGER.info(
                f"Guardian Active ({"enforce" if enforce else "audit"}) — loaded from policy manifest"
            )
            LOGGER.info("=" * 60)
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/] {str(e)}."
                f" Run [bold]mellea-skills ingest[/] or "
                f"[bold]mellea-skills certify[/] first for Guardian protection. "
            )
            LOGGER.info("Running unguarded.")

    try:
        # run the given fixture
        report = _run_single_fixture(pipeline_fn, fixture)

        # output
        console.print("[bold blue]OUTPUT:[/]")
        print(report)

    except Exception as e:
        LOGGER.error(f"Pipeline run failed: {str(e)}")
    finally:
        deregister_plugins(guardian_plugin, audit_plugin)


def full_pipeline(
    pipeline_dir: Path,
    fixture_id: Optional[str] = None,
    enforce: bool = False,
    model: Optional[str] = None,
    guardian_model: Optional[str] = None,
    inference_engine: InferenceEngineType = InferenceEngineType.OLLAMA,
):
    """Full Certification Pipeline for Mellea skill

    Args:
        pipeline_dir (Path): Compiled Mellea skill pipeline directory.
        fixture_id (Optional[str], optional): Specify a fixture to run with the certification process. Defaults to None.
        enforce (bool, optional): Run pipeline in enforce mode (block on risk detection). Defaults to False.
        model (Optional[str], optional): Model to use for Risk and Action Identification. The `inference_engine` param must support the model. If set to None, the default model for the inference engine will be used.
        guardian_model (Optional[str], optional): Model to use for Risk Assessment. The `inference_engine` param must support the model. If set to None, the default guardian model for the inference engine will be used.
        inference_engine (InferenceEngineType, optional): Service to use for LLM inference. Defaults to InferenceEngineType.OLLAMA.
    """

    # Verify skill pipeline directory exists
    if pipeline_dir.exists():
        # Verify that given path is a directory
        if not pipeline_dir.is_dir():
            raise ValueError(
                "The specified path is not a directory. Please note that the certify command only accepts a compiled skill directory."
            )
    else:
        raise FileNotFoundError(f"Skill pipeline directory not found: {pipeline_dir}")

    # Load skill pipeline
    pipeline_fn = load_skill_pipeline(pipeline_dir)

    # Load fixtures from the pipeline directory
    fixtures = load_fixtures(pipeline_dir)

    # Get the desired fixture
    if fixture_id is None:
        fixture = fixtures[0]
    else:
        fixture = None
        for f in fixtures:
            if fixture_id == f["id"]:
                fixture = f
                break
        if fixture is None:
            available = [f["id"] for f in fixtures]
            raise ValueError(f"Unknown fixture '{fixture_id}'. Available: {available}")

    mode_label = "ENFORCE" if enforce else "AUDIT"
    print()
    LOGGER.info("=" * 70)
    LOGGER.info("MelleaSkills — Full Pipeline [%s mode]", mode_label)
    LOGGER.info("=" * 70)
    print()

    # ── Step 1: Ingest SKILL.md ────────────────────────────────────────

    # load and create ai atlas nexus instance
    from ai_atlas_nexus.library import AIAtlasNexus

    from mellea_skills_compiler.certification import skill_to_use_case
    from mellea_skills_compiler.certification.classification import (
        classify_skill_sensitivity,
    )

    nexus_data_path = get_data_path()
    nexus = AIAtlasNexus(base_dir=nexus_data_path)

    # Get skill spec-file path
    spec_path: Path = pipeline_dir / SpecFileFormat.SKILL_FILE_MD
    if not spec_path.exists():
        raise FileNotFoundError(f"Skill spec file not found: {spec_path}")

    LOGGER.info("Step 1: Ingesting %s...", spec_path.name)
    parsed = parse_spec_file(spec_path)
    fm = parsed["frontmatter"]
    sensitivity = classify_skill_sensitivity(
        fm.get("allowed-tools", []), parsed["body"]
    )
    use_case = skill_to_use_case(parsed, sensitivity)

    LOGGER.info("  Name: %s", fm.get("name", "unknown"))
    LOGGER.info("  Tools: %s", fm.get("allowed-tools", []))
    LOGGER.info("  Sensitivity: %s", sensitivity["tier_display"])
    LOGGER.info("  Use-case: %.100s...", use_case)
    print()
    LOGGER.info("  Fixture: %s", fixture["id"])
    print()

    # Certification artifacts output directory
    output_dir = pipeline_dir.parent / "audit"
    output_dir.mkdir(exist_ok=True)

    # ── Step 2: Generate policy manifest from Nexus ────────────────────
    LOGGER.info("Step 2: Identifying risks via AI Atlas Nexus...")

    # Genereate policy manifest
    manifest = generate_policy_manifest(use_case, nexus, model, inference_engine)
    manifest_path = output_dir / "policy_manifest.json"
    manifest.to_json(manifest_path)

    # Generate policy markdown
    policy_md = generate_policy_markdown(manifest)
    policy_path = output_dir / "POLICY.md"
    policy_path.write_text(policy_md)

    # Log policy artifacts
    LOGGER.info("Guardian risks: %d", len(manifest.risks))
    for r in manifest.risks:
        tier = "native" if r.is_native else "custom"
        LOGGER.info("    - %s (%s)", r.name, tier)
    LOGGER.info("Governance actions: %d", len(manifest.governance_actions))
    LOGGER.info("Policy manifest: %s", manifest_path)
    LOGGER.info("Policy document: %s", policy_path)

    # ── Step 3: Configure plugins from manifest ───────────────────────
    LOGGER.info(
        "Step 3: Configuring Guardian hooks from policy manifest (%s)...", mode_label
    )
    guardian_plugin, audit_plugin = register_plugins(
        manifest, output_dir, enforce, guardian_model, inference_engine
    )

    # ── Step 4: Run the decomposed pipeline ───────────────────────────
    LOGGER.info("Step 4: Running decomposed pipeline from %s...", pipeline_dir.name)
    LOGGER.info("Guardian checks every generation (pre + post).")

    try:
        # run the given fixture
        report = _run_single_fixture(pipeline_fn, fixture)
        if report:
            # Write the pipeline's report (works for any Pydantic model)
            report_json_path = output_dir / "pipeline_report.json"
            if hasattr(report, "model_dump_json"):
                report_json_path.write_text(report.model_dump_json(indent=2))
            else:
                report_json_path.write_text(json.dumps(report, indent=2, default=str))

            LOGGER.info("Pipeline report: %s", report_json_path.name)
    except Exception as e:
        LOGGER.error(f"Pipeline run failed: {str(e)}")
    finally:
        deregister_plugins(guardian_plugin, audit_plugin)

    # ── Step 5: Guardian verdict summary ──────────────────────────────
    LOGGER.info("=" * 70)
    LOGGER.info("Step 5: Guardian Verdict Summary")
    LOGGER.info("=" * 70)
    total_verdicts = len(guardian_plugin.all_verdicts)
    flagged_verdicts = [v for v in guardian_plugin.all_verdicts if v.label == "Yes"]
    passed_verdicts = [v for v in guardian_plugin.all_verdicts if v.label == "No"]
    failed_verdicts = [v for v in guardian_plugin.all_verdicts if v.label == "Failed"]

    LOGGER.info("  Total verdicts: %d", total_verdicts)
    LOGGER.info("  Passed (No risk): %d", len(passed_verdicts))
    LOGGER.info("  Flagged (Risk detected): %d", len(flagged_verdicts))
    if failed_verdicts:
        LOGGER.info("  Failed (Guardian error): %d", len(failed_verdicts))
    LOGGER.info("")

    if flagged_verdicts:
        LOGGER.info("  Flagged risks:")
        for v in flagged_verdicts:
            LOGGER.info(
                "    [!!] risk=%-25s raw=%.50s", v.risk, v.raw_output.replace("\n", " ")
            )
    LOGGER.info("")

    # ── Step 6: Audit trail summary ───────────────────────────────────
    LOGGER.info("=" * 70)
    LOGGER.info("Step 6: Audit Trail Summary")
    LOGGER.info("=" * 70)
    summary = audit_plugin.summary()
    for k, v in summary.items():
        LOGGER.info("  %s: %s", k, v)
    LOGGER.info("")

    # ── Step 7: Compliance classification ─────────────────────────────
    LOGGER.info("=" * 70)
    LOGGER.info("Step 7: Compliance Classification")
    LOGGER.info("=" * 70)
    compliance = classify_governance_requirements(manifest, nexus)
    counts = compliance.counts
    total = sum(counts.values())
    LOGGER.info(
        "  AUTOMATED: %d  |  PARTIAL: %d  |  MANUAL: %d  (total: %d)",
        counts["AUTOMATED"],
        counts["PARTIAL"],
        counts["MANUAL"],
        total,
    )
    LOGGER.info("")

    # ── Step 8: Certification report ──────────────────────────────────
    LOGGER.info("=" * 70)
    LOGGER.info("Step 8: Generating Certification Report")
    LOGGER.info("=" * 70)
    audit_entries = load_audit_trail(audit_plugin.log_path)
    cert_report = generate_certification_report(
        manifest,
        compliance,
        audit_entries,
        str(audit_plugin.log_path),
    )
    cert_path = output_dir / "CERTIFICATION.md"
    cert_path.write_text(cert_report)
    LOGGER.info("  Certification report: %s", cert_path.name)
    LOGGER.info("  Based on %d audit trail events", len(audit_entries))
    LOGGER.info("")

    # ── Final summary ─────────────────────────────────────────────────
    any_risk = any(v.label == "Yes" for v in guardian_plugin.all_verdicts)
    LOGGER.info("=" * 70)
    skill_name = fm.get("name", "unknown")
    LOGGER.info("COMPLETE — %s [%s]", skill_name, mode_label)
    LOGGER.info("=" * 70)
    LOGGER.info("")
    LOGGER.info("  Skill: %s (%s)", skill_name, sensitivity["tier_display"])
    LOGGER.info("  Fixture: %s", fixture["id"])
    LOGGER.info("  Guardian risks: %d (from Nexus)", len(manifest.risks))
    LOGGER.info(
        "  Guardian verdicts: %d total, %d flagged",
        total_verdicts,
        len(flagged_verdicts),
    )
    LOGGER.info("  Audit events: %d", len(audit_entries))
    LOGGER.info(
        "  Compliance: AUTOMATED=%d PARTIAL=%d MANUAL=%d",
        counts["AUTOMATED"],
        counts["PARTIAL"],
        counts["MANUAL"],
    )
    LOGGER.info("")
    LOGGER.info("  Artifacts:")
    LOGGER.info("  Artifacts in %s/:", output_dir)
    LOGGER.info("    manifest.json        — Policy manifest")
    LOGGER.info("    POLICY.md            — Policy document")
    LOGGER.info("    pipeline_report.json — Pipeline output")
    LOGGER.info("    audit_trail.jsonl    — Runtime audit trail")
    LOGGER.info("    CERTIFICATION.md     — Certification report")
    LOGGER.info("")

    if any_risk:
        LOGGER.warning("  STATUS: RISKS DETECTED — review audit trail")
    else:
        LOGGER.info("  STATUS: ALL CHECKS PASSED")
        LOGGER.warning("  STATUS: RISKS DETECTED — review audit trail")
