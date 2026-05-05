"""Post-lint fixture smoke-check (Step 7's `--run` mode).

Executes one fixture (or all, if `all_fixtures=True`) from the compiled
package and classifies the outcome into one of three verdicts:

  - `passed`  — fixture executed without exception.
  - `failed`  — fixture raised an exception other than backend-unreachable.
                Exit code 12 (distinct from lint failure exit code 11).
  - `skipped` — LLM backend unreachable (Ollama not running, timeout, auth
                error). Exit code 0 with a stderr warning so CI without an
                LLM stays green while still nudging local users.

Writes intermediate/step_7b_report.json. Does NOT trigger the repair loop —
fixture failures require human review per `mellea-fy-validate.md`.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from mellea_skills_compiler.toolkit.file_utils import (
    load_fixtures,
    load_skill_pipeline,
)
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


@dataclass
class SmokeFixtureResult:
    fixture_id: str
    verdict: str  # "passed" | "failed" | "skipped"
    duration_seconds: float
    skipped_reason: Optional[str] = None
    failure_message: Optional[str] = None
    failure_traceback: Optional[str] = None


@dataclass
class SmokeRunResult:
    overall_verdict: str  # "passed" | "failed" | "skipped"
    fixtures: List[SmokeFixtureResult] = field(default_factory=list)
    package_path: str = ""
    checked_at: str = ""

    @property
    def exit_code(self) -> int:
        if self.overall_verdict == "failed":
            return 12
        return 0


def _classify_exception(exc: BaseException) -> Optional[str]:
    """Return a non-None 'skipped' reason if the exception indicates backend unreachable.

    Detection covers the common forms: stdlib socket/connection errors, httpx/
    requests library variants (by class name to avoid hard imports), HTTP
    auth failures, and timeouts.
    """
    cls_name = type(exc).__name__
    cls_module = type(exc).__module__

    # stdlib network errors
    if isinstance(exc, (ConnectionError, ConnectionRefusedError, ConnectionAbortedError, ConnectionResetError)):
        return f"backend unreachable: {cls_name}: {exc}"
    if isinstance(exc, TimeoutError):
        return f"backend unreachable: timeout: {exc}"

    # httpx / requests / urllib3 — name-matched to avoid import dependencies
    if cls_name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "PoolTimeout", "RemoteProtocolError"):
        return f"backend unreachable: {cls_module}.{cls_name}: {exc}"
    if cls_name == "ConnectionError" and cls_module.startswith(("requests", "urllib3", "httpx", "httpcore")):
        return f"backend unreachable: {cls_module}.{cls_name}: {exc}"

    # HTTP auth from various libs (string match — APIs vary widely)
    text = str(exc)
    if "401" in text or "403" in text or "unauthorized" in text.lower() or "authentication failed" in text.lower():
        return f"backend unreachable: authentication failed (check API key or env vars): {exc}"

    return None


def _run_one_fixture(pipeline_fn, fixture: Dict[str, Any]) -> SmokeFixtureResult:
    fixture_id = fixture.get("id", "<unknown>")
    started = time.time()
    try:
        context = fixture["context"]
        if isinstance(context, dict):
            pipeline_fn(**context)
        else:
            pipeline_fn(context)
    except BaseException as exc:  # noqa: BLE001 — we re-classify all
        duration = time.time() - started
        skipped_reason = _classify_exception(exc)
        if skipped_reason:
            LOGGER.warning(
                "Fixture smoke-check skipped — %s. Re-run `mellea-skills validate <pkg> --run` "
                "once the backend is up to verify runtime behaviour.",
                skipped_reason,
            )
            return SmokeFixtureResult(
                fixture_id=fixture_id,
                verdict="skipped",
                duration_seconds=duration,
                skipped_reason=skipped_reason,
            )
        return SmokeFixtureResult(
            fixture_id=fixture_id,
            verdict="failed",
            duration_seconds=duration,
            failure_message=f"{type(exc).__name__}: {exc}",
            failure_traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
    return SmokeFixtureResult(
        fixture_id=fixture_id,
        verdict="passed",
        duration_seconds=time.time() - started,
    )


def run_smoke_check(package_dir: Path, all_fixtures: bool = False) -> SmokeRunResult:
    """Execute one (or all) fixtures and write step_7b_report.json.

    Args:
        package_dir: compiled package directory (e.g. `<skill>/<name>_mellea`).
        all_fixtures: if False (default), only the first fixture in ALL_FIXTURES
            is executed. If True, every fixture is run sequentially.
    """
    pipeline_fn = load_skill_pipeline(package_dir)
    fixtures = load_fixtures(package_dir)

    targets = fixtures if all_fixtures else fixtures[:1]

    fixture_results: List[SmokeFixtureResult] = []
    for fixture in targets:
        fixture_results.append(_run_one_fixture(pipeline_fn, fixture))

    if any(r.verdict == "failed" for r in fixture_results):
        overall = "failed"
    elif all(r.verdict == "skipped" for r in fixture_results):
        overall = "skipped"
    else:
        overall = "passed"

    run = SmokeRunResult(
        overall_verdict=overall,
        fixtures=fixture_results,
        package_path=str(package_dir),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )

    intermediate = package_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    (intermediate / "step_7b_report.json").write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "checked_at": run.checked_at,
                "package_path": run.package_path,
                "overall_verdict": run.overall_verdict,
                "fixtures": [asdict(r) for r in fixture_results],
            },
            indent=2,
        )
    )

    return run
