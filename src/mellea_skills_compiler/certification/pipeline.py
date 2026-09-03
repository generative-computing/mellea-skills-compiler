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
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mellea.plugins import PluginViolationError
from pydantic import TypeAdapter
from rich.console import Console

from mellea_skills_compiler.certification.classification import (
    classify_governance_requirements,
)
from mellea_skills_compiler.certification.data import get_data_path
from mellea_skills_compiler.certification.input_resolver import resolve_input
from mellea_skills_compiler.certification.policy import (
    generate_policy_manifest,
    generate_policy_markdown,
    load_policy_manifest,
)
from mellea_skills_compiler.certification.report import (
    generate_certification_report,
    load_audit_trail,
)
from mellea_skills_compiler.enums import (
    GuardianMode,
    InferenceEngineType,
    NexusRiskSource,
    SpecFileFormat,
)
from mellea_skills_compiler.inference import InferenceService
from mellea_skills_compiler.models import (
    Fixture,
    FixtureResult,
    GuardianVerdict,
    PolicyManifest,
    RunResult,
)
from mellea_skills_compiler.plugins.audit import AuditTrailPlugin
from mellea_skills_compiler.plugins.guardian import (
    GuardianPlugin,
    GuardianPluginFactory,
)
from mellea_skills_compiler.toolkit.file_utils import (
    load_fixtures,
    load_skill_pipeline,
    parse_spec_file,
)
from mellea_skills_compiler.toolkit.logging import configure_logger


console: Console = Console(log_time=True)

LOGGER: Logger = configure_logger()


def _dump_fixture_results(
    results_path: Path, fixture_results: List[FixtureResult]
) -> None:
    with open(results_path, "w", encoding="utf-8") as result_file:
        json.dump(
            TypeAdapter(List[FixtureResult]).dump_python(fixture_results),
            result_file,
            indent=4,
            default=str,
        )


def _run_single_fixture(pipeline_fn: Callable, fixture: Fixture):
    try:
        if isinstance(fixture.context, Dict):
            output = pipeline_fn(**fixture.context)
        else:
            output = pipeline_fn(fixture.context)
    except PluginViolationError as e:
        return FixtureResult.blocked(fixture=fixture, e=e)
    except Exception as e:
        return FixtureResult.failed(fixture=fixture, e=e)

    return FixtureResult.success(fixture=fixture, output=output)


def run_pipeline(
    pipeline_dir: Path,
    guardian_mode: GuardianMode,
    fixture_id: Optional[str] = None,
    input: Optional[str] = None,
    guardian_model: Optional[str] = None,
    inference_engine_type: InferenceEngineType = InferenceEngineType.OLLAMA,
) -> RunResult:
    """Full Certification Pipeline for Mellea skill

    Args:
        pipeline_dir (Path): Compiled Mellea skill pipeline directory.
        guardian_mode (GuardianMode): Run pipeline in enforce mode (block on risk detection), audit mode or with guardian assessment disabled.
        fixture_id (str, optional): fixture_id to run through the Mellea pipeline. If None, uses input parameter.
        input (str, optional): input specification to run through the Mellea pipeline. Supports five input types.
        guardian_model (Optional[str], optional): Model to use for Risk Assessment. The `inference_engine` param must support the model. If set to None, the default guardian model for the inference engine will be used.
        inference_engine_type (InferenceEngineType, optional): Service to use for LLM inference. Defaults to InferenceEngineType.OLLAMA.

    Returns:
        RunResult: Result object containing run directory, input parameters, guardian verdicts, and status.
    """

    # Gather input parameters for audit purpose
    input_parameters: dict[str, Any] = locals().copy()

    run_dir: Optional[Path] = None
    guardian_plugin: Optional[GuardianPlugin] = None
    audit_plugin: Optional[AuditTrailPlugin] = None

    try:
        # Verify skill pipeline directory exists
        if pipeline_dir.exists():
            # Verify that given path is a directory
            if not pipeline_dir.is_dir():
                raise ValueError(
                    "The specified path is not a directory. Please note that the run command only accepts a compiled skill directory."
                )
        else:
            raise FileNotFoundError(
                f"Skill pipeline directory not found: {pipeline_dir}"
            )

        # Create the current run directory
        run_dir = (
            pipeline_dir.parent
            / "runs"
            / datetime.now().strftime(format="%d-%m-%Y_%H-%M-%S")
        )
        run_dir.mkdir(parents=True, exist_ok=True)

        if guardian_mode == GuardianMode.DISABLED:
            LOGGER.info("Guardian checks disabled (--no-guardian)")
        else:
            # Get audit directory with the manifest file
            manifest_path: Optional[Path] = None
            audit_parent: Path = Path(pipeline_dir.parent / "audit")
            if audit_parent.exists():
                for audit_dir in reversed(list(audit_parent.glob("*"))):
                    if (audit_dir / "policy_manifest.json").exists():
                        manifest_path = audit_dir / "policy_manifest.json"
                        break

            try:
                if not manifest_path:
                    raise FileNotFoundError(
                        f"Unable to find audit directory with a manifest file in {pipeline_dir.parent}."
                    )
                else:
                    # Load existing policy manifest
                    manifest: PolicyManifest = load_policy_manifest(manifest_path)

                    # Configure plugins from manifest
                    LOGGER.info(
                        "Configuring Guardian hooks from Policy Manifest...",
                    )
                    guardian_plugin = GuardianPluginFactory.create(
                        guardian_mode,
                        manifest.risks,
                        InferenceService.guardian_engine(
                            guardian_model, inference_engine_type
                        ),
                    )
                    guardian_plugin.register()
                    audit_plugin = AuditTrailPlugin(
                        log_path=run_dir / "audit_trail.jsonl",
                        guardian_plugin=guardian_plugin,
                    )
                    audit_plugin.register()
            except Exception as e:
                console.print(
                    f"[yellow]Warning:[/] {str(e)}"
                    f" Run [bold]mellea-skills ingest[/] or "
                    f"[bold]mellea-skills certify[/] first for Guardian protection. "
                )
                LOGGER.info("Running unguarded.")

        # Load skill pipeline
        pipeline_fn: Callable = load_skill_pipeline(pipeline_dir)

        # Resolve fixture from possible sources
        fixture: Fixture = resolve_input(
            pipeline_fn=pipeline_fn,
            input=input,
            fixture_id=fixture_id,
            fixtures=load_fixtures(pipeline_dir) if fixture_id else None,
        )

        # run given fixture
        fixture_result: FixtureResult = _run_single_fixture(pipeline_fn, fixture)

        # Write fixture results if available
        if fixture_result:
            fixture_results_path: Path = run_dir / "fixture_results.json"
            _dump_fixture_results(
                results_path=fixture_results_path, fixture_results=[fixture_result]
            )

        # output
        console.print(f"\n[bold blue]OUTPUT:[/]\n{fixture_result.output}")
        return RunResult.success(
            run_dir=run_dir,
            input_parameters=input_parameters,
            guardian_verdicts=guardian_plugin.summary() if guardian_plugin else None,
        )
    except Exception as e:
        LOGGER.error(f"Pipeline run failed - {str(e)}")
        return RunResult.failed(
            run_dir=run_dir,
            input_parameters=input_parameters,
            guardian_verdicts=guardian_plugin.summary() if guardian_plugin else None,
            error_details={"type": type(e).__name__, "message": str(e)},
        )
    finally:
        if guardian_plugin:
            guardian_plugin.deregister()
        if audit_plugin:
            audit_plugin.deregister()


def full_pipeline(
    pipeline_dir: Path,
    guardian_mode: GuardianMode,
    n_fixtures: int = 3,
    risk_model: Optional[str] = None,
    guardian_model: Optional[str] = None,
    inference_engine_type: InferenceEngineType = InferenceEngineType.OLLAMA,
) -> RunResult:
    """Full Certification Pipeline for Mellea skill

    Args:
        pipeline_dir (Path): Compiled Mellea skill pipeline directory.
        guardian_mode (GuardianMode): Run pipeline in enforce mode (block on risk detection), audit mode or with guardian assessment disabled.
        n_fixtures (int): Specify the number of fixtures to evaluate for the certification process. Defaults to 3.
        risk_model (Optional[str], optional): Model to use for Risk and Action Identification. The `inference_engine` param must support the model. If set to None, the default model for the inference engine will be used.
        guardian_model (Optional[str], optional): Model to use for Risk Assessment. The `inference_engine` param must support the model. If set to None, the default guardian model for the inference engine will be used.
        inference_engine_type (InferenceEngineType, optional): Service to use for LLM inference. Defaults to InferenceEngineType.OLLAMA.

    Returns:
        RunResult: Result object containing run directory, input parameters, guardian verdicts, and status.
    """

    # Gather input parameters for audit purpose
    input_parameters = locals().copy()

    audit_dir: Optional[Path] = None
    guardian_plugin: Optional[GuardianPlugin] = None
    audit_plugin: Optional[AuditTrailPlugin] = None

    try:
        # Verify skill pipeline directory exists
        if pipeline_dir.exists():
            # Verify that given path is a directory
            if not pipeline_dir.is_dir():
                raise ValueError(
                    "The specified path is not a directory. Please note that the certify command only accepts a compiled skill directory."
                )
        else:
            raise FileNotFoundError(
                f"Skill pipeline directory not found: {pipeline_dir}"
            )

        # Create the current audit directory
        audit_dir = (
            pipeline_dir.parent / "audit" / datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        )
        audit_dir.mkdir(parents=True, exist_ok=True)

        # Load skill pipeline
        pipeline_fn = load_skill_pipeline(pipeline_dir)

        # Load fixtures from the pipeline directory
        fixtures = load_fixtures(pipeline_dir)

        print()
        LOGGER.info("=" * 70)
        LOGGER.info(f"MelleaSkills — Full Pipeline [{guardian_mode} mode]")
        LOGGER.info("=" * 70)

        # load and create ai atlas nexus instance
        from ai_atlas_nexus.library import AIAtlasNexus

        from mellea_skills_compiler.certification import skill_to_use_case
        from mellea_skills_compiler.certification.classification import (
            classify_skill_sensitivity,
        )

        # ── Get skill spec-file path ──────────────────────────
        spec_path: Path = pipeline_dir / SpecFileFormat.SKILL_FILE_MD
        if not spec_path.exists():
            raise FileNotFoundError(f"Skill spec file not found: {spec_path}")

        # ── Parse skill specification ──────────────────────────
        print()
        LOGGER.info(f"Ingesting... {spec_path.name}")
        parsed = parse_spec_file(spec_path)
        frontmatter = parsed["frontmatter"]
        LOGGER.info("  Name: %s", frontmatter.get("name", "unknown"))
        LOGGER.info("  Description: %.100s", frontmatter.get("description", ""))
        LOGGER.info("  Tools: %s", frontmatter.get("allowed-tools", []))

        # ── Sensitivity classification ──────────────────────────
        print()
        LOGGER.info("Tool Sensitivity Classification")
        sensitivity = classify_skill_sensitivity(
            frontmatter.get("allowed-tools", []), parsed["body"]
        )
        LOGGER.info("  Tier: %s", sensitivity["tier_display"])
        LOGGER.info("  Operations: %s", sensitivity["operations"])
        if sensitivity["capabilities"]:
            LOGGER.info("  Capabilities: %s", sensitivity["capabilities"])

        # ── Compose use-case description ────────────────────────
        print()
        LOGGER.info("Generating Use-case")
        use_case = skill_to_use_case(parsed, sensitivity)
        LOGGER.info(f"  Description: {use_case}")

        # ── Step 1: Generate policy manifest using AI Atlas Nexus ────────────────────
        print()
        LOGGER.info("Identifying risks via AI Atlas Nexus...")
        nexus_data_path = get_data_path()
        nexus = AIAtlasNexus(base_dir=nexus_data_path)
        manifest: PolicyManifest = generate_policy_manifest(
            use_case,
            nexus,
            inference_engine=InferenceService.risk_engine(
                risk_model, inference_engine_type
            ),
        )
        manifest_path: Path = audit_dir / "policy_manifest.json"
        manifest.to_json(path=manifest_path)

        # ── Step 2: Generate policy markdown ────────────────────
        policy_md: str = generate_policy_markdown(manifest)
        policy_path: Path = audit_dir / "POLICY.md"
        policy_path.write_text(data=policy_md)

        # Log policy artifacts
        LOGGER.info("Policy manifest: %s", manifest_path)
        LOGGER.info("Policy document: %s", policy_path)

        # ── Step 3: Configure plugins from manifest ───────────────────────
        print()
        LOGGER.info(
            "Configuring Guardian hooks from Policy Manifest...",
        )
        guardian_plugin = GuardianPluginFactory.create(
            guardian_mode,
            manifest.risks,
            InferenceService.guardian_engine(guardian_model, inference_engine_type),
        )
        guardian_plugin.register()
        audit_plugin = AuditTrailPlugin(
            log_path=audit_dir / "audit_trail.jsonl", guardian_plugin=guardian_plugin
        )
        audit_plugin.register()

        # ── Step 4: Run the decomposed pipeline ───────────────────────────

        # Get random `n_fixtures` fixtures to evaluate
        sample_fixtures: List[Fixture] = (
            random.sample(fixtures, n_fixtures) if len(fixtures) >= 3 else fixtures
        )

        print()
        LOGGER.info("Running decomposed pipeline from %s...", pipeline_dir.name)
        LOGGER.info("  - Fixtures identified:")
        for fixture in sample_fixtures:
            LOGGER.info(f"      - {fixture.id}")
        LOGGER.info(
            f"  - Guardian checks [{guardian_mode}] every generation (pre + post)."
        )
        LOGGER.info("  - Audit Trail checks every end points (pre + post).")

        # run input fixtures
        fixture_results: List[FixtureResult] = []
        try:
            with ThreadPoolExecutor() as executor:

                # Submit all fixtures
                future_to_fixture = {
                    executor.submit(_run_single_fixture, pipeline_fn, f): f
                    for f in sample_fixtures
                }

                # Collect results as they complete
                for future in as_completed(fs=future_to_fixture):
                    fixture: Fixture = future_to_fixture[future]
                    fixture_result: FixtureResult = future.result(timeout=300)
                    fixture_results.append(fixture_result)

                LOGGER.info(f"✓ Executed {len(sample_fixtures)} fixture(s)")
        except Exception as e:
            raise RuntimeError(
                f"✗ Fixtures execution failed with error: {str(e)}"
            ) from e

        # Write fixture results if available
        fixture_summary: Optional[Counter[str]] = None
        if fixture_results:
            fixture_summary = Counter(f.status for f in fixture_results)
            fixture_results_path: Path = audit_dir / "fixture_results.json"
            _dump_fixture_results(fixture_results_path, fixture_results)

            # ── Fixture Execution Summary ──────────────────────────────
            LOGGER.info("")
            LOGGER.info("=" * 70)
            LOGGER.info("Fixture Execution Summary")
            LOGGER.info("=" * 70)
            LOGGER.info("Total: %d", len(fixture_results))

            LOGGER.info(f"Passed: {fixture_summary['success']}")
            LOGGER.info(f"Blocked (Risk detected): {fixture_summary['blocked']}")
            LOGGER.info(f"Failed: {fixture_summary['failed']}")
            LOGGER.info(f"Fixture Results: {fixture_results_path}")

            if len(fixture_results) == fixture_summary["failed"]:
                message = "🔴 All fixtures failed. Certification process aborted."
                LOGGER.error(message)
                return RunResult.failed(
                    run_dir=audit_dir,
                    input_parameters=input_parameters,
                    guardian_verdicts=guardian_plugin.summary(),
                    error_details={"type": "Fixture", "message": message},
                )

        # ── Step 5: Guardian verdict summary ──────────────────────────────
        LOGGER.info("")
        LOGGER.info("=" * 70)
        LOGGER.info("Guardian Verdict Summary")
        LOGGER.info("=" * 70)

        verdict_summary = guardian_plugin.summary()
        LOGGER.info("Total verdicts: %d", len(verdict_summary["all_verdicts"]))
        LOGGER.info("Passed (No risk): %d", len(verdict_summary["passed_verdicts"]))
        LOGGER.info(
            "Flagged (Risk detected): %d", len(verdict_summary["flagged_verdicts"])
        )
        if verdict_summary["flagged_verdicts"]:
            risk_stage_counts = {}
            for verdict in verdict_summary["flagged_verdicts"]:
                risk_stage_counts.setdefault(verdict.risk, Counter())[
                    verdict.hook_stage
                ] += 1
            for risk, stage_counts in risk_stage_counts.items():
                stage_msgs = ", ".join(
                    f"{count} in {stage}-assessment"
                    for stage, count in stage_counts.items()
                )
                LOGGER.info(f"  [!!] {risk}: {stage_msgs}")
        LOGGER.info(
            "Failed (Guardian error): %d", len(verdict_summary["failed_verdicts"])
        )

        # ── Step 6: Audit trail summary ───────────────────────────────────
        LOGGER.info("")
        LOGGER.info("=" * 70)
        LOGGER.info("Audit Trail Summary")
        LOGGER.info("=" * 70)

        audit_summary = audit_plugin.summary()
        for k, v in audit_summary.items():
            LOGGER.info("%s: %s", k.replace("_", " ").title(), v)

        # ── Step 7: Compliance classification ─────────────────────────────
        LOGGER.info("")
        LOGGER.info("=" * 70)
        LOGGER.info("Compliance Classification")
        LOGGER.info("=" * 70)

        compliance = classify_governance_requirements(manifest, nexus)
        counts = compliance.counts
        total = sum(counts.values())
        LOGGER.info(
            "AUTOMATED: %d  |  PARTIAL: %d  |  MANUAL: %d  (total: %d)",
            counts["AUTOMATED"],
            counts["PARTIAL"],
            counts["MANUAL"],
            total,
        )

        # ── Step 8: Certification report ──────────────────────────────────
        LOGGER.info("")
        LOGGER.info("=" * 70)
        LOGGER.info("Certification Report")
        LOGGER.info("=" * 70)

        audit_entries = load_audit_trail(audit_plugin.log_path)
        cert_report = generate_certification_report(
            manifest,
            compliance,
            audit_entries,
            str(audit_plugin.log_path),
        )
        cert_path = audit_dir / "CERTIFICATION.md"
        cert_path.write_text(cert_report)
        LOGGER.info(f"Report generated: {cert_path}")

        # ── Final summary ─────────────────────────────────────────────────
        print("")
        LOGGER.info("=" * 70)
        skill_name = frontmatter.get("name", "unknown")
        LOGGER.info(f"COMPLETE — {skill_name} [{guardian_mode} mode]")
        LOGGER.info("=" * 70)
        print("")
        LOGGER.info("Skill: %s (%s)", skill_name, sensitivity["tier_display"])
        LOGGER.info("Fixtures: %s", len(sample_fixtures))
        LOGGER.info("Guardian risks: %d (from Nexus)", len(manifest.risks))
        LOGGER.info(
            "Guardian verdicts: %d total, %d Passed, %d flagged, %d failed",
            len(verdict_summary["all_verdicts"]),
            len(verdict_summary["passed_verdicts"]),
            len(verdict_summary["flagged_verdicts"]),
            len(verdict_summary["failed_verdicts"]),
        )
        LOGGER.info("Audit events: %d", len(audit_entries))
        LOGGER.info("")
        LOGGER.info("Compliance:")
        LOGGER.info(f"  AUTOMATED={counts['AUTOMATED']}")
        LOGGER.info(f"  PARTIAL={counts['PARTIAL']}")
        LOGGER.info(f"  MANUAL={counts['MANUAL']}")
        LOGGER.info("")
        LOGGER.info(f"Artifacts written to {audit_dir}")
        for file in [f for f in audit_dir.iterdir() if f.is_file()]:
            LOGGER.info(f"  {file.name}")

        warnings = []
        if manifest.risks and all(
            risk.source == NexusRiskSource.DEFAULT_FALLBACK for risk in manifest.risks
        ):
            risk_names = [risk.name for risk in manifest.risks]
            warnings.append(
                f"Generic fail-safe risk screening applied: {risk_names}. "
                "Risks are not specific to the intended use-case."
            )
        if fixture_summary and fixture_summary["failed"] > 0:
            success_count = fixture_summary["success"]
            total_count = len(fixture_results)
            pass_rate = (success_count / total_count) * 100
            warnings.append(
                f"Low fixture pass rate: {pass_rate:.1f}% ({success_count}/{total_count} passed). "
                "Consider reviewing failed fixtures before proceeding."
            )

        if warnings:
            warning_msg = "\n\n⚠️  CERTIFICATION WARNINGS:\n"
            for warning in warnings:
                warning_msg += f"  • {warning}\n"
            LOGGER.warning(warning_msg)

        has_flagged: List[GuardianVerdict] = verdict_summary["flagged_verdicts"]
        has_failed: List[GuardianVerdict] = verdict_summary["failed_verdicts"]

        if has_failed:
            LOGGER.warning("STATUS: RISK ASSESSMENT FAILURE — review audit trail")
        if has_flagged:
            LOGGER.warning("STATUS: RISKS DETECTED — review audit trail")
        if not (has_flagged or has_failed):
            LOGGER.info("ALL STATUS CHECKS PASSED")

        # Return RunResult with the summary of the run
        return RunResult.success(
            run_dir=audit_dir,
            input_parameters=input_parameters,
            guardian_verdicts=guardian_plugin.summary() if guardian_plugin else None,
        )
    except Exception as e:
        LOGGER.error(f"Certify command failed - {str(e)}")
        return RunResult.failed(
            run_dir=audit_dir,
            input_parameters=input_parameters,
            guardian_verdicts=guardian_plugin.summary() if guardian_plugin else None,
            error_details={"type": type(e).__name__, "message": str(e)},
        )
    finally:
        if guardian_plugin:
            guardian_plugin.deregister()
        if audit_plugin:
            audit_plugin.deregister()
