"""Deterministic grounding artifact generation for the mellea-fy pipeline.

This module produces `mellea_api_ref.json` and `mellea_doc_index.json` in the
compile pipeline's intermediate directory before the slash command runs. The
slash command itself runs with `--allowed-tools Read,Write,Edit` and so cannot
introspect the installed `mellea` package or fetch `https://docs.mellea.ai/`.
Doing it here means Steps 2.5e and 2.5f of the slash command have real
grounding data to consume rather than silently degrading to static fallbacks.

Both functions are idempotent and cache results under
`~/.cache/mellea-skills-compiler/`. The api_ref cache is keyed by the installed
mellea version; the doc_index cache uses a configurable TTL (default 24h) with
a stale-cache fallback if the network is unreachable.
"""

import importlib
import importlib.metadata
import inspect
import json
import os
import pkgutil
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()

CACHE_DIR = Path.home() / ".cache" / "mellea-skills-compiler"

# Modules always introspected, regardless of dependency_plan.json contents.
CORE_MODULES = {
    "mellea.stdlib.requirements",
    "mellea.stdlib.sampling",
    "mellea.backends.model_options",
}

# Static fallback for `forbidden_param_names` if the genslot symbol is not
# importable. Source: mellea-fy-deps.md:134-137 (snapshot 2026-04-28).
_FORBIDDEN_PARAM_NAMES_FALLBACK = [
    "f_args",
    "f_kwargs",
    "m",
    "context",
    "backend",
    "model_options",
    "strategy",
    "precondition_requirements",
    "requirements",
]

# Static fallback for the doc_index when docs.mellea.ai is unreachable and no
# cached copy exists. Source: mellea-fy-deps.md:217-242 (snapshot 2026-04-28).
_DOC_PAGES_FALLBACK = [
    "/getting-started/installation",
    "/tutorials/01-your-first-generative-program",
    "/tutorials/04-making-agents-reliable",
    "/concepts/generative-functions",
    "/concepts/requirements-system",
    "/concepts/instruct-validate-repair",
    "/concepts/mobjects-and-mify",
    "/concepts/context-and-sessions",
    "/how-to/enforce-structured-output",
    "/how-to/write-custom-verifiers",
    "/how-to/use-async-and-streaming",
    "/how-to/use-context-and-sessions",
    "/how-to/configure-model-options",
    "/how-to/use-images-and-vision",
    "/how-to/build-a-rag-pipeline",
    "/guide/backends-and-configuration",
    "/guide/tools-and-agents",
    "/advanced/inference-time-scaling",
    "/integrations/ollama",
    "/integrations/openai",
    "/integrations/bedrock",
    "/integrations/watsonx",
    "/integrations/huggingface",
    "/integrations/vertex-ai",
    "/integrations/langchain",
]


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via a sibling .tmp file + os.replace.

    Uses os.replace so concurrent compiles in different processes cannot leave
    a half-written file.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content)
    os.replace(tmp, path)


def _load_dependency_plan_targets(intermediate_dir: Path) -> set[str]:
    """Extract target module names from `dependency_plan.json` if present.

    Each entry's `target` field has shape `module.path:symbol`; we keep only
    the module portion. Returns an empty set if the file is missing or malformed.
    """
    plan_path = intermediate_dir / "dependency_plan.json"
    if not plan_path.exists():
        return set()
    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    targets: set[str] = set()
    for dep in plan.get("plan", []):
        target = dep.get("target")
        if target:
            targets.add(target.split(":")[0])
    return targets


def _introspect_mellea(referenced_modules: set[str]) -> dict[str, dict[str, Any]]:
    """Walk the installed `mellea` package and collect public callable signatures.

    Restricted to the union of CORE_MODULES and `referenced_modules` (from
    dependency_plan.json). Modules that fail to import or symbols that resolve
    to objects without inspectable signatures are skipped silently.
    """
    try:
        mellea_pkg = importlib.import_module("mellea")
    except ImportError:
        return {}

    all_mellea = {
        m.name
        for m in pkgutil.walk_packages(path=mellea_pkg.__path__, prefix="mellea.")
    }
    to_scan = all_mellea & (CORE_MODULES | referenced_modules)

    api_ref: dict[str, dict[str, Any]] = {}
    for module_name in sorted(to_scan):
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            continue
        symbols: dict[str, Any] = {}
        for name, obj in inspect.getmembers(mod, callable):
            if name.startswith("_"):
                continue
            try:
                symbols[name] = {"signature": f"{name}{inspect.signature(obj)}"}
            except (ValueError, TypeError):
                pass
        if symbols:
            api_ref[module_name] = symbols
    return api_ref


def _extract_forbidden_param_names() -> list[str]:
    """Pull the live disallowed-param list from genslot, with static fallback."""
    try:
        from mellea.stdlib.components.genslot import (  # type: ignore
            _disallowed_param_names,
        )

        return list(_disallowed_param_names)
    except (ImportError, AttributeError):
        return list(_FORBIDDEN_PARAM_NAMES_FALLBACK)


def _load_compatibility_entries(mellea_version: str) -> list[dict[str, Any]]:
    """Load `.claude/data/compatibility.yaml` and filter to applicable entries.

    Filtering uses `packaging.specifiers.SpecifierSet` against the installed
    mellea version. An `applies_when` of "*" or missing means "always applies".
    Returns an empty list if the file is missing or unparseable.
    """
    compat_path = Path(".claude/data/compatibility.yaml")
    if not compat_path.exists():
        return []
    try:
        import yaml  # type: ignore

        compat = yaml.safe_load(compat_path.read_text()) or {}
    except Exception:
        return []
    try:
        from packaging.specifiers import SpecifierSet  # type: ignore
    except ImportError:
        return list(compat.get("entries", []))

    entries: list[dict[str, Any]] = []
    for entry in compat.get("entries", []):
        applies = entry.get("applies_when", "*")
        if applies == "*":
            entries.append(entry)
            continue
        try:
            if mellea_version in SpecifierSet(applies):
                entries.append(entry)
        except Exception:
            # If the specifier is malformed, include the entry rather than drop it.
            entries.append(entry)
    return entries


def _grounding_unavailable_payload() -> str:
    """JSON payload written when `mellea` is not installed (deps.md:163-175)."""
    return json.dumps(
        {
            "format_version": "1.0",
            "mellea_version": None,
            "grounding_unavailable": True,
            "modules": {},
            "forbidden_param_names": list(_FORBIDDEN_PARAM_NAMES_FALLBACK),
            "compatibility": [],
        },
        indent=2,
    )


def write_mellea_api_ref(intermediate_dir: Path, refresh: bool = False) -> Path:
    """Write `mellea_api_ref.json` to `intermediate_dir`.

    Cached by installed mellea version under
    `~/.cache/mellea-skills-compiler/api_ref_<version>.json`. If `mellea` is
    not installed, writes the `grounding_unavailable: true` shape and returns.
    """
    out_path = intermediate_dir / "mellea_api_ref.json"

    try:
        version = importlib.metadata.version("mellea")
    except importlib.metadata.PackageNotFoundError:
        LOGGER.warning(
            "mellea package not installed; writing grounding_unavailable api_ref"
        )
        _atomic_write(out_path, _grounding_unavailable_payload())
        return out_path

    cache_path = CACHE_DIR / f"api_ref_{version}.json"

    if cache_path.exists() and not refresh:
        LOGGER.info("Using cached mellea_api_ref for version %s", version)
        _atomic_write(out_path, cache_path.read_text())
        return out_path

    LOGGER.info("Introspecting mellea %s for api_ref", version)
    referenced = _load_dependency_plan_targets(intermediate_dir)
    modules = _introspect_mellea(referenced)
    forbidden = _extract_forbidden_param_names()
    compatibility = _load_compatibility_entries(version)

    payload = {
        "format_version": "1.0",
        "mellea_version": version,
        "grounding_unavailable": False,
        "modules": modules,
        "forbidden_param_names": forbidden,
        "compatibility": compatibility,
    }
    serialized = json.dumps(payload, indent=2)

    _atomic_write(cache_path, serialized)
    _atomic_write(out_path, serialized)
    return out_path


def _fetch_doc_pages() -> list[str]:
    """Fetch and parse navigation hrefs from docs.mellea.ai. Raises on failure."""
    with urllib.request.urlopen("https://docs.mellea.ai/", timeout=10) as resp:
        html = resp.read().decode()
    return sorted(set(re.findall(r'href="(/[^"]+)"', html)))


def write_mellea_doc_index(
    intermediate_dir: Path, refresh: bool = False, ttl_hours: int = 24
) -> Path:
    """Write `mellea_doc_index.json` to `intermediate_dir`.

    Cached at `~/.cache/mellea-skills-compiler/doc_index.json` with a
    `ttl_hours` TTL (default 24h). On fetch failure, reuses a stale cache if
    one exists; otherwise writes the static 2026-04-28 fallback list.
    """
    out_path = intermediate_dir / "mellea_doc_index.json"
    cache_path = CACHE_DIR / "doc_index.json"

    # Cache hit within TTL — reuse without touching the network.
    if cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text())
            fetched_at_str = cached.get("fetched_at", "")
            fetched_at = datetime.fromisoformat(fetched_at_str)
            age = datetime.now(timezone.utc) - fetched_at
            if age.total_seconds() < ttl_hours * 3600:
                _atomic_write(out_path, cache_path.read_text())
                return out_path
        except (OSError, ValueError, json.JSONDecodeError):
            # Treat a corrupt cache as a miss; we'll try to refetch.
            pass

    # Need a fresh fetch (cache missing, expired, corrupt, or refresh=True).
    try:
        doc_pages = _fetch_doc_pages()
        LOGGER.info("Fetched %d doc pages from docs.mellea.ai", len(doc_pages))
        payload = {
            "format_version": "1.0",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "https://docs.mellea.ai/",
            "fetch_status": "ok",
            "doc_pages": doc_pages,
        }
        serialized = json.dumps(payload, indent=2)
        _atomic_write(cache_path, serialized)
        _atomic_write(out_path, serialized)
        return out_path
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Fetch failed. Prefer a stale cache (better than nothing) over the
        # hardcoded fallback.
        if cache_path.exists():
            try:
                cached_text = cache_path.read_text()
                cached = json.loads(cached_text)
                LOGGER.warning(
                    "docs.mellea.ai unreachable; using stale cache from %s",
                    cached.get("fetched_at", "<unknown>"),
                )
                _atomic_write(out_path, cached_text)
                return out_path
            except (OSError, json.JSONDecodeError):
                pass

        LOGGER.warning(
            "docs.mellea.ai unreachable and no cache; using static fallback "
            "(2026-04-28 snapshot)"
        )
        payload = {
            "format_version": "1.0",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "https://docs.mellea.ai/",
            "fetch_status": f"failed: {exc}",
            "doc_pages": list(_DOC_PAGES_FALLBACK),
        }
        _atomic_write(out_path, json.dumps(payload, indent=2))
        return out_path
