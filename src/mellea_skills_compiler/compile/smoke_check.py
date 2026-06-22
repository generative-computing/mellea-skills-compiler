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
import re
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


# Known mismatches between Python import names and PyPI package names.
# Extend as new mismatches are observed in compiled skills. The minimum entry
# point is one direction: import-name -> PyPI-name; the lookup is applied
# during _is_declared_dependency only when a direct/normalised match fails.
_IMPORT_TO_PYPI: Dict[str, str] = {
    "docx": "python-docx",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "magic": "python-magic",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
}


def _declared_dependency_names(skill_dir: Path) -> Optional[set]:
    """Return the set of canonical dep names from skill_dir/pyproject.toml.

    Returns ``None`` if pyproject.toml is missing or unreadable — the caller
    treats that as 'cannot determine declared deps' and falls through to the
    failed-classification path.
    """
    pyproject = skill_dir / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover — project requires 3.11+
        return None
    try:
        data = tomllib.loads(pyproject.read_text())
    except Exception:  # noqa: BLE001 — malformed TOML treated as 'unknown'
        return None
    deps = data.get("project", {}).get("dependencies", []) or []
    names: set = set()
    for dep in deps:
        if not isinstance(dep, str):
            continue
        # PEP 508 head extraction: name [extras] [version-spec] [; markers]
        head = re.split(r"[\s<>=!~\[;]", dep, maxsplit=1)[0].strip().lower()
        if head:
            names.add(head)
            names.add(head.replace("-", "_"))
            names.add(head.replace("_", "-"))
    return names


def _is_declared_dependency(missing_module: str, skill_dir: Path) -> bool:
    """True if ``missing_module`` corresponds to a dep in skill_dir/pyproject.toml.

    Matching strategy: lowercase + hyphen/underscore normalisation, then a
    small hardcoded import-name -> PyPI-name table for known mismatches
    (e.g. ``docx`` -> ``python-docx``, ``yaml`` -> ``pyyaml``).
    """
    declared = _declared_dependency_names(skill_dir)
    if not declared:
        return False
    name = missing_module.lower()
    candidates = {name, name.replace("_", "-"), name.replace("-", "_")}
    mapped = _IMPORT_TO_PYPI.get(missing_module) or _IMPORT_TO_PYPI.get(name)
    if mapped:
        mapped_lower = mapped.lower()
        candidates |= {
            mapped_lower,
            mapped_lower.replace("-", "_"),
            mapped_lower.replace("_", "-"),
        }
    return bool(declared & candidates)


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


def _classify_exception(
    exc: BaseException, skill_dir: Optional[Path] = None
) -> Optional[str]:
    """Return a non-None 'skipped' reason if the exception is environmental.

    Two classes of skip:

    1. Backend unreachable — stdlib socket/connection errors, httpx/requests
       library variants (by class name to avoid hard imports), HTTP auth
       failures, and timeouts.
    2. Declared dependency missing from the compile-process venv — a
       ``ModuleNotFoundError`` whose missing module corresponds to a dep
       declared in ``skill_dir/pyproject.toml``. The skill compiles fine;
       the user just needs ``pip install -e .`` before runtime verification.
       Distinguished from a real code bug (LLM imports something it didn't
       declare), which is left to fall through to the failed path.
    """
    cls_name = type(exc).__name__
    cls_module = type(exc).__module__

    # Declared-dependency-missing — environmental, not a code bug.
    # Checked first so a ModuleNotFoundError that LOOKS network-like (e.g.
    # ConnectionError from a missing urllib3) doesn't get misclassified.
    if isinstance(exc, ModuleNotFoundError) and skill_dir is not None:
        missing = (getattr(exc, "name", None) or "").split(".")[0]
        if missing and _is_declared_dependency(missing, skill_dir):
            return (
                f"declared dependency {missing!r} not installed in the "
                f"compile-process venv. The skill's pyproject.toml declares "
                f"it; run `pip install -e .` in the skill directory and "
                f"re-run the smoke check to verify runtime behaviour."
            )

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


def _run_one_fixture(
    pipeline_fn,
    fixture: Dict[str, Any],
    skill_dir: Optional[Path] = None,
) -> SmokeFixtureResult:
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
        skipped_reason = _classify_exception(exc, skill_dir=skill_dir)
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

    # The skill root sits one level above the compiled package; pyproject.toml
    # lives at the skill root (Rule OUT-3). Pass it through so ModuleNotFoundError
    # classification can distinguish declared-dep-missing from real-bug.
    skill_dir = package_dir.parent

    fixture_results: List[SmokeFixtureResult] = []
    for fixture in targets:
        fixture_results.append(
            _run_one_fixture(pipeline_fn, fixture, skill_dir=skill_dir)
        )

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
