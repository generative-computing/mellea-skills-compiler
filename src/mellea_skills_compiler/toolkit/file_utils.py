import importlib
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from rich.console import Console

from mellea_skills_compiler.toolkit.logging import configure_logger


console = Console()
LOGGER = configure_logger()


# ── SKILL.md parser ────────────────────────────────────────────────
def parse_spec_file(spec_path: Path) -> dict:
    """Parse a SKILL.md file into frontmatter dict + markdown body."""
    text = spec_path.read_text()

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {"frontmatter": {}, "body": text, "path": str(spec_path)}

    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()

    # Normalize allowed-tools: string → list
    tools_raw = frontmatter.get("allowed-tools", [])
    if isinstance(tools_raw, str):
        if "," in tools_raw:
            frontmatter["allowed-tools"] = [
                t.strip() for t in tools_raw.split(",") if t.strip()
            ]
        else:
            frontmatter["allowed-tools"] = tools_raw.split()
    elif not isinstance(tools_raw, list):
        frontmatter["allowed-tools"] = []

    # OpenClaw convention: tools in metadata.openclaw.requires.bins/anyBins
    openclaw_req = (
        frontmatter.get("metadata", {}).get("openclaw", {}).get("requires", {})
    )
    extra_tools = openclaw_req.get("bins", []) + openclaw_req.get("anyBins", [])
    existing = set(frontmatter.get("allowed-tools", []))
    for t in extra_tools:
        if t not in existing:
            frontmatter.setdefault("allowed-tools", []).append(t)
            existing.add(t)

    return {"frontmatter": frontmatter, "body": body, "path": str(spec_path)}


# Dynamically import the pipeline from the skill directory
def load_skill_pipeline(pipeline_dir: Path):

    # Add parent directory to sys.path to set PYTHONPAYH
    sys.path.insert(0, str(pipeline_dir.parent))

    try:
        skill_pipeline = importlib.import_module(f"{pipeline_dir.name}.pipeline")
    except ModuleNotFoundError as e:
        raise Exception(
            f"Error: The `pipeline.py` module is missing from the pipeline directory - {pipeline_dir}"
        )
    finally:
        # Remove parent directory from sys.path
        sys.path.pop(0)

    # Find the main entry point.
    # Resolution order:
    #   1. Locally-defined `run_pipeline` — the documented canonical entry
    #      (`melleafy.json:entry_signature` always names this) and the only
    #      name guaranteed to be the entry point regardless of any helper
    #      `run_*` functions that may be defined alongside it.
    #   2. Any other locally-defined `run_*` function — first match by
    #      sorted dir() order.
    #   3. Any imported `run_*` function (functions whose `__module__` is
    #      not the pipeline module itself).
    #
    # The earlier "first locally-defined run_* wins" rule picked the
    # alphabetically-first match, which silently bound `run_assessment_method`,
    # `run_analysis`, etc. as the entry whenever the canonical `run_pipeline`
    # sorted after a helper. The smoke-check would then call the helper with
    # the fixture's kwargs and raise TypeError on signature mismatch.
    module_name = skill_pipeline.__name__

    canonical = getattr(skill_pipeline, "run_pipeline", None)
    if callable(canonical) and getattr(canonical, "__module__", None) == module_name:
        return canonical

    run_fn = None
    imported_run_fn = None
    for attr_name in dir(skill_pipeline):
        if attr_name.startswith("run_") and callable(
            getattr(skill_pipeline, attr_name)
        ):
            fn = getattr(skill_pipeline, attr_name)
            if getattr(fn, "__module__", None) == module_name:
                run_fn = fn
                break
            elif imported_run_fn is None:
                imported_run_fn = fn

    # Fall back to an imported run_* if no locally-defined one was found
    if run_fn is None:
        run_fn = imported_run_fn

    if run_fn is None:
        raise Exception("No run_* function found in %s", pipeline_dir)

    return run_fn


# ── Load Fixtures ────────────────────────────────────────────────
def load_fixtures(pipeline_dir: Path) -> List[Dict]:
    """Load fixtures from the skill's fixtures/ directory.

    Supports two conventions:
    - ALL_FIXTURES: list of factory functions returning (inputs, id, description)
    - FIXTURES: list of dicts with 'id' and 'context' keys
    """

    """Find fixtures/ directly under skill_dir, or inside a *_mellea/ subdirectory."""
    fixtures_dir = pipeline_dir / "fixtures"
    if not fixtures_dir.is_dir():
        for child in pipeline_dir.iterdir():
            if child.is_dir() and child.name.endswith("_mellea"):
                fixtures_dir = child / "fixtures"
                if fixtures_dir.is_dir():
                    break

    if not fixtures_dir.is_dir():  # or not (fixtures_dir / "__init__.py").exists()
        raise Exception(
            f"No fixtures directory found in {pipeline_dir}. Please run `mellea-skills compile` to compile the skill first."
        )

    fixtures = None
    sys.path.insert(0, str(fixtures_dir.parent))
    try:
        mod = importlib.import_module(fixtures_dir.name)
        # Convention 1: FIXTURES list of dicts (e.g., test_fixtures.py)
        if hasattr(mod, "FIXTURES"):
            fixtures = mod.FIXTURES

        # Convention 2: ALL_FIXTURES list of factory functions (mellea-fy generated)
        if hasattr(mod, "ALL_FIXTURES"):
            fixtures = []
            for factory in mod.ALL_FIXTURES:
                inputs, fixture_id, description = factory()
                fixtures.append(
                    {
                        "id": fixture_id,
                        "context": inputs,
                        "description": description,
                    }
                )
    except ImportError:
        raise Exception(
            f"The `__init__.py` module is missing from the fixture directory - {fixtures_dir}"
        )
    finally:
        sys.path.pop(0)

    if not fixtures:
        raise Exception(f"No valid FIXTURES found in {fixtures_dir}")
    else:
        return fixtures


def mirror_dir_contents_to_target(
    source_dir: Path,
    target_dir: Path,
    include_only: Optional[List[str]] = None,
    ignore_patterns: Optional[List[str]] = None,
) -> List[str]:
    """Mirror directory contents from source to target directory.

    Copies all files and subdirectories from source_dir into target_dir,
    excluding items in the ignore list. If `include_only` provided, copy only those items.
    Skips copying if the target directory is inside the source to prevent infinite recursion.

    Args:
        source_dir Path: Source directory to copy from
        target_dir Path: Destination directory (created if it doesn't exist)
        include_only List[str], optional: Include items in the given list only. Default is None.
        ignore_patterns List[str], optional: List of file/directory names to skip. Default is None.

    Returns:
        List of item names that were successfully copied

    Raises:
        OSError: If file operations fail

    Example:
        >>> mirror_dir_contents_to_target(
        ...     Path("/skill"),
        ...     Path("/skill/skill_mellea"),
        ...     ignore_patterns=["audit", "pyproject.toml"]
        ... )
        ['scripts', 'references', 'spec.md']
    """

    mirrored: List[str] = []

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    for source in source_dir.iterdir():
        # If include_only provided, skip items NOT in it
        if include_only and source.name not in include_only:
            continue

        # Skip items in ignore_patterns
        if ignore_patterns and source.name in ignore_patterns:
            continue

        # Skip recursion
        if source == target_dir or source.is_relative_to(target_dir):
            continue

        target = target_dir / source.name
        try:
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
            mirrored.append(source.name)
        except Exception as e:
            LOGGER.warning(f"Failed to mirror {source.name}: {e}")

    return mirrored
