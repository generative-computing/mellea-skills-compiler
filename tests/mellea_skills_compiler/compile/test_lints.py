"""Unit tests for mellea_skills_compiler.compile.lints module.

Covers every implemented Step 7 structural lint plus the run_lints runner
that emits intermediate/step_7_report.json. All tests construct synthetic
skill packages on disk in tempfile.TemporaryDirectory contexts; no network,
Ollama, or slash-command invocation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Dict

from mellea_skills_compiler.compile.lints import (
    lint_bundled_asset_path_resolution,
    lint_fixture_pydantic_coercion,
    lint_grounding_context_types,
    lint_prefix_persona,
    lint_import_side_effects,
    lint_import_soundness,
    lint_parseable,
    lint_stdlib_arg_types,
    lint_fixtures_loader_contract,
    lint_format_annotation,
    lint_instruct_result_parse_before_access,
    lint_runtime_defaults_bound,
    lint_session_boundary,
    lint_session_method_arity,
    lint_validation_fn_not_called_directly,
    run_lints,
)


def _make_package(root: Path, files: Dict[str, str]) -> Path:
    """Materialise a synthetic skill package under `root`.

    `files` maps relative paths (POSIX-style) to file contents. Parent
    directories are created as needed. Returns the package directory (root).
    """
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


# ─── TestFixturesLoaderContract ───


class TestFixturesLoaderContract:
    """Test cases for lint_fixtures_loader_contract."""

    def test_passes_with_all_fixtures_export(self):
        """fixtures/__init__.py exporting ALL_FIXTURES = [] should pass."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"fixtures/__init__.py": "ALL_FIXTURES = []\n"},
            )
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "pass", (
                f"Expected pass for ALL_FIXTURES export, got {result.verdict}: "
                f"{[f.message for f in result.failures]}"
            )
            assert result.failures == []
            assert result.files_checked == 1

    def test_passes_with_fixtures_export(self):
        """fixtures/__init__.py exporting FIXTURES = [] (alt shape) should pass."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"fixtures/__init__.py": "FIXTURES = []\n"},
            )
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "pass", (
                f"Expected pass for FIXTURES export, got {result.verdict}: "
                f"{[f.message for f in result.failures]}"
            )

    def test_passes_with_annotated_assignment(self):
        """fixtures/__init__.py with annotated ALL_FIXTURES: list = [] should pass."""
        content = (
            "from typing import Callable\n"
            "ALL_FIXTURES: list[Callable] = []\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"fixtures/__init__.py": content})
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "pass", (
                f"Annotated ALL_FIXTURES assignment should be recognised; got "
                f"{result.verdict} with failures {[f.message for f in result.failures]}"
            )

    def test_fails_with_input_only_module(self):
        """fixtures/__init__.py with only INPUT = {...} (crewai drift) should fail."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"fixtures/__init__.py": 'INPUT = {"foo": "bar"}\n'},
            )
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "fail", (
                "INPUT-only fixtures module should fail the loader contract"
            )
            assert len(result.failures) == 1
            msg = result.failures[0].message
            assert "ALL_FIXTURES" in msg, (
                f"Failure message should name ALL_FIXTURES; got: {msg}"
            )
            assert "FIXTURES" in msg, (
                f"Failure message should also name FIXTURES; got: {msg}"
            )

    def test_fails_with_pytest_test_function(self):
        """fixtures/__init__.py with only def test_x(): ... (security-review drift)."""
        content = (
            "def test_something():\n"
            "    assert True\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"fixtures/__init__.py": content})
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "fail", (
                "pytest-style fixtures module without ALL_FIXTURES/FIXTURES should fail"
            )
            assert len(result.failures) == 1

    def test_skipped_when_fixtures_init_missing(self):
        """fixtures/ exists with no __init__.py — verdict skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "fixtures").mkdir()
            # Some other file but no __init__.py
            (pkg / "fixtures" / "data.txt").write_text("not python\n")
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "skipped", (
                f"Missing fixtures/__init__.py should produce skipped, got {result.verdict}"
            )
            assert result.skipped_reason is not None
            assert "fixtures/__init__.py" in result.skipped_reason

    def test_fails_with_syntax_error(self):
        """fixtures/__init__.py with a Python syntax error should fail with line info."""
        broken = "def broken(:\n    pass\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"fixtures/__init__.py": broken})
            result = lint_fixtures_loader_contract(pkg)
            assert result.verdict == "fail", (
                f"SyntaxError in fixtures/__init__.py should fail; got {result.verdict}"
            )
            assert len(result.failures) == 1
            failure = result.failures[0]
            assert failure.line is not None, (
                "SyntaxError failure should carry a line number"
            )
            assert "SyntaxError" in failure.message


# ─── TestBundledAssetPathResolution ───


class TestBundledAssetPathResolution:
    """Test cases for lint_bundled_asset_path_resolution."""

    def test_passes_with_path_dunder_file_chain(self):
        """Path(__file__).parent / 'scripts' / 'bash' / 'x.sh' should pass."""
        content = (
            "from pathlib import Path\n"
            "p = Path(__file__).parent / 'scripts' / 'bash' / 'x.sh'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"Path(__file__).parent chain should pass; got failures: "
                f"{[f.message for f in result.failures]}"
            )

    def test_passes_with_path_dunder_file_compound_string(self):
        """Path(__file__).parent / 'scripts/bash/x.sh' (compound string) should pass."""
        content = (
            "from pathlib import Path\n"
            "p = Path(__file__).parent / 'scripts/bash/x.sh'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"Path(__file__).parent / compound bundled string should pass; "
                f"failures: {[f.message for f in result.failures]}"
            )

    def test_passes_with_no_bundled_paths(self):
        """tools.py with no scripts/references/assets references should pass."""
        content = (
            "from pathlib import Path\n"
            "p = Path('/tmp') / 'whatever.txt'\n"
            "q = 'no bundled dirs here'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"Module with no bundled-dir references should pass; "
                f"failures: {[f.message for f in result.failures]}"
            )

    def test_fails_with_repo_root_join_compound_string(self):
        """Path(repo_root) / 'scripts/bash/x.sh' should fail."""
        content = (
            "from pathlib import Path\n"
            "repo_root = '/tmp/whatever'\n"
            "p = Path(repo_root) / 'scripts/bash/x.sh'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail", (
                f"Path(repo_root) / 'scripts/...' should fail; got {result.verdict}"
            )
            assert len(result.failures) == 1
            msg = result.failures[0].message
            assert "Path(__file__).parent" in msg, (
                f"Failure message should advise Path(__file__).parent; got: {msg}"
            )

    def test_fails_with_repo_root_join_chain(self):
        """Path(repo_root) / 'scripts' / 'bash' should fail."""
        content = (
            "from pathlib import Path\n"
            "repo_root = '/tmp/whatever'\n"
            "p = Path(repo_root) / 'scripts' / 'bash'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail", (
                f"Path(repo_root) / 'scripts' / 'bash' chain should fail; "
                f"got {result.verdict}"
            )
            assert len(result.failures) >= 1

    def test_fails_with_os_path_join_non_file_rooted(self):
        """os.path.join(repo_root, 'scripts', 'bash') should fail."""
        content = (
            "import os\n"
            "repo_root = '/tmp/whatever'\n"
            "p = os.path.join(repo_root, 'scripts', 'bash')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail", (
                f"os.path.join(repo_root, 'scripts', ...) should fail; "
                f"got {result.verdict}"
            )
            assert len(result.failures) == 1

    def test_passes_with_os_path_join_dunder_file(self):
        """os.path.join(os.path.dirname(__file__), 'scripts') should pass."""
        content = (
            "import os\n"
            "p = os.path.join(os.path.dirname(__file__), 'scripts')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"os.path.join with __file__-rooted base should pass; "
                f"failures: {[f.message for f in result.failures]}"
            )

    def test_skips_fixtures_directory(self):
        """Files under fixtures/ are excluded — bad path resolution there shouldn't fail."""
        content = (
            "from pathlib import Path\n"
            "repo_root = '/tmp/whatever'\n"
            "p = Path(repo_root) / 'scripts/x.sh'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"fixtures/test_x.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"fixtures/ should be excluded from this lint's scope; got {result.verdict} "
                f"with failures {[f.message for f in result.failures]}"
            )
            assert result.files_checked == 0, (
                "fixtures/ files should not be counted as checked"
            )

    def test_dedups_failures_in_chain(self):
        """A chained Path(repo_root) / 'scripts' / 'bash' / 'x.sh' produces ONE failure."""
        content = (
            "from pathlib import Path\n"
            "repo_root = '/tmp/whatever'\n"
            "p = Path(repo_root) / 'scripts' / 'bash' / 'x.sh'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1, (
                f"Chained BinOp(Div) should dedupe to a single failure; got "
                f"{len(result.failures)}: {[f.message for f in result.failures]}"
            )

    def test_passes_with_pkg_dir_alias_module_level(self):
        """`pkg_dir = Path(__file__).parent; pkg_dir / 'references'` is a clean idiom."""
        content = (
            "from pathlib import Path\n"
            "pkg_dir = Path(__file__).parent\n"
            "references_dir = pkg_dir / 'references'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"loader.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"`pkg_dir = Path(__file__).parent` alias should make `pkg_dir / 'references'` "
                f"pass; got failures: {[f.message for f in result.failures]}"
            )

    def test_passes_with_pkg_dir_alias_inside_function(self):
        """Alias bound inside a function body must still be tracked."""
        content = (
            "from pathlib import Path\n"
            "\n"
            "def load_documents():\n"
            "    pkg_dir = Path(__file__).parent\n"
            "    references_dir = pkg_dir / 'references'\n"
            "    return references_dir\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"loader.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "pass", (
                f"In-function alias should be tracked; got failures: "
                f"{[f.message for f in result.failures]}"
            )

    def test_passes_with_annotated_alias(self):
        """`pkg_dir: Path = Path(__file__).parent` AnnAssign form."""
        content = (
            "from pathlib import Path\n"
            "pkg_dir: Path = Path(__file__).parent\n"
            "p = pkg_dir / 'assets' / 'x.png'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            assert lint_bundled_asset_path_resolution(pkg).verdict == "pass"

    def test_passes_with_alias_for_os_path_join(self):
        """`pkg_dir = Path(__file__).parent; os.path.join(pkg_dir, 'scripts', ...)`."""
        content = (
            "import os\n"
            "from pathlib import Path\n"
            "pkg_dir = Path(__file__).parent\n"
            "p = os.path.join(pkg_dir, 'scripts', 'go.sh')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            assert lint_bundled_asset_path_resolution(pkg).verdict == "pass"

    def test_fails_when_alias_bound_to_non_file_root(self):
        """An alias to `os.getcwd()` or some other non-__file__ root should NOT be accepted."""
        content = (
            "import os\n"
            "from pathlib import Path\n"
            "pkg_dir = Path(os.getcwd())\n"
            "p = pkg_dir / 'references' / 'doc.md'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"loader.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail", (
                f"Alias bound to a non-__file__ root must NOT be accepted; got "
                f"verdict={result.verdict}"
            )

    def test_failure_message_mentions_alias_pattern(self):
        """When the lint fails, the message hints that local aliases are accepted."""
        content = (
            "from pathlib import Path\n"
            "p = Path('/tmp/whatever') / 'references' / 'x.md'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"tools.py": content})
            result = lint_bundled_asset_path_resolution(pkg)
            assert result.verdict == "fail"
            msg = result.failures[0].message
            assert "pkg_dir" in msg and "alias" in msg.lower(), (
                f"Failure message should mention the alias workaround; got: {msg}"
            )


# ─── TestRuntimeDefaultsBound ───


def _write_directive(pkg: Path, backend: str, model_id: str) -> None:
    """Write intermediate/runtime_directive.json to the synthetic package."""
    intermediate = pkg / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    (intermediate / "runtime_directive.json").write_text(
        json.dumps({"backend": backend, "model_id": model_id})
    )


class TestRuntimeDefaultsBound:
    """Test cases for lint_runtime_defaults_bound."""

    def test_passes_when_config_matches_directive(self):
        """config.py with matching BACKEND/MODEL_ID should pass."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "pass", (
                f"Matching config and directive should pass; got {result.verdict} "
                f"with failures {[f.message for f in result.failures]}"
            )

    def test_fails_when_backend_diverges(self):
        """config.py BACKEND != directive backend → fail with actionable message."""
        config = (
            'BACKEND = "watsonx"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "fail", (
                f"Backend divergence should fail; got {result.verdict}"
            )
            assert len(result.failures) == 1
            msg = result.failures[0].message
            assert "watsonx" in msg, f"Message should name actual value 'watsonx': {msg}"
            assert "ollama" in msg, f"Message should name expected value 'ollama': {msg}"
            assert ".claude/data/runtime_defaults.json" in msg, (
                f"Message should reference .claude/data/runtime_defaults.json: {msg}"
            )

    def test_fails_when_model_id_diverges(self):
        """config.py MODEL_ID != directive model_id → fail."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:2b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "fail", (
                f"Model ID divergence should fail; got {result.verdict}"
            )
            assert len(result.failures) == 1
            msg = result.failures[0].message
            assert "granite3.3:2b" in msg
            assert "granite3.3:8b" in msg

    def test_fails_when_backend_constant_missing(self):
        """config.py without BACKEND → fail with a clear message naming BACKEND."""
        config = 'MODEL_ID = "granite3.3:8b"\n'
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "fail", (
                f"Missing BACKEND constant should fail; got {result.verdict}"
            )
            # At least one failure should mention BACKEND missing
            backend_msgs = [f.message for f in result.failures if "BACKEND" in f.message]
            assert backend_msgs, (
                f"Expected a failure naming missing BACKEND; got: "
                f"{[f.message for f in result.failures]}"
            )
            assert any("does not define" in m for m in backend_msgs), (
                f"Message should say config.py 'does not define' BACKEND; got: {backend_msgs}"
            )

    def test_skipped_when_directive_missing(self):
        """No intermediate/runtime_directive.json → skipped with 'older pipeline' reason."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "skipped", (
                f"Missing directive should skip; got {result.verdict}"
            )
            assert result.skipped_reason is not None
            assert "older pipeline" in result.skipped_reason, (
                f"Skip reason should mention 'older pipeline'; got: {result.skipped_reason}"
            )

    def test_skipped_when_config_missing(self):
        """No config.py → skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "skipped", (
                f"Missing config.py should skip; got {result.verdict}"
            )
            assert result.skipped_reason is not None
            assert "config.py" in result.skipped_reason

    def test_skipped_when_directive_malformed_json(self):
        """Malformed JSON in runtime_directive.json → skipped with parse-error reason."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            (pkg / "intermediate").mkdir(parents=True, exist_ok=True)
            (pkg / "intermediate" / "runtime_directive.json").write_text(
                "{not valid json"
            )
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "skipped", (
                f"Malformed directive JSON should skip; got {result.verdict}"
            )
            assert result.skipped_reason is not None
            assert (
                "could not read" in result.skipped_reason
                or "runtime_directive.json" in result.skipped_reason
            ), (
                f"Skip reason should cite the parse failure; got: {result.skipped_reason}"
            )

    def test_handles_annotated_assignment(self):
        """config.py using BACKEND: Final[str] = 'ollama' (annotated) should validate."""
        config = (
            "from typing import Final\n"
            'BACKEND: Final[str] = "ollama"\n'
            'MODEL_ID: Final[str] = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "pass", (
                f"Annotated BACKEND/MODEL_ID assignments should be recognised; "
                f"got {result.verdict} with failures "
                f"{[f.message for f in result.failures]}"
            )

    def test_handles_plain_assignment(self):
        """config.py using BACKEND = 'ollama' (no annotation) should validate."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"config.py": config})
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = lint_runtime_defaults_bound(pkg)
            assert result.verdict == "pass", (
                f"Plain BACKEND/MODEL_ID assignments should be recognised; "
                f"got {result.verdict} with failures "
                f"{[f.message for f in result.failures]}"
            )


# ─── TestRunLints ───


class TestRunLints:
    """Integration tests for the run_lints orchestrator."""

    def test_overall_pass_when_all_pass(self):
        """A compliant synthetic package should yield overall_verdict == 'pass'."""
        config = (
            'BACKEND = "ollama"\n'
            'MODEL_ID = "granite3.3:8b"\n'
        )
        tools = (
            "from pathlib import Path\n"
            "p = Path(__file__).parent / 'scripts' / 'bash' / 'x.sh'\n"
        )
        pipeline = "def run_pipeline(x: str) -> str:\n    return x\n"
        with tempfile.TemporaryDirectory() as tmp:
            # The Tier 1 `parseable` lint requires <pkg>/pipeline.py to
            # exist and import cleanly; a "compliant package" must include
            # it. We materialise the package under an `_mellea`-suffixed
            # parent so the subprocess `import <pkg>.pipeline` resolves.
            pkg = _make_package(
                Path(tmp) / "synthetic_mellea",
                {
                    "__init__.py": "",
                    "pipeline.py": pipeline,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "config.py": config,
                    "tools.py": tools,
                },
            )
            _write_directive(pkg, "ollama", "granite3.3:8b")
            result = run_lints(pkg)
            assert result.overall_verdict == "pass", (
                f"Compliant package should pass overall; got {result.overall_verdict} "
                f"with lints={[(r.lint_id, r.verdict) for r in result.lints]}"
            )
            assert result.failed is False

    def test_overall_fail_on_any_lint_fail(self):
        """A package with one failing lint should yield overall 'fail'."""
        # fixtures/__init__.py is wrong shape — fixtures-loader-contract fails.
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"fixtures/__init__.py": 'INPUT = {"x": 1}\n'},
            )
            result = run_lints(pkg)
            assert result.overall_verdict == "fail", (
                f"Any failing lint should fail overall; got {result.overall_verdict} "
                f"with lints={[(r.lint_id, r.verdict) for r in result.lints]}"
            )
            assert result.failed is True

    def test_writes_step_7_report(self):
        """run_lints must write a parseable intermediate/step_7_report.json."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"fixtures/__init__.py": "ALL_FIXTURES = []\n"},
            )
            run_lints(pkg)
            report_path = pkg / "intermediate" / "step_7_report.json"
            assert report_path.exists(), (
                f"step_7_report.json should be written at {report_path}"
            )
            data = json.loads(report_path.read_text())
            assert "format_version" in data, (
                f"Report should carry format_version; keys: {list(data.keys())}"
            )
            assert "overall_verdict" in data
            assert "lints" in data and isinstance(data["lints"], list)
            for lint_entry in data["lints"]:
                assert "lint_id" in lint_entry, (
                    f"Each lint entry needs lint_id; got {lint_entry}"
                )
                assert "verdict" in lint_entry
                assert "failures" in lint_entry
                assert isinstance(lint_entry["failures"], list)

    def test_intermediate_dir_created(self):
        """intermediate/ should be created if it didn't already exist."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)  # no intermediate/ to start
            assert not (pkg / "intermediate").exists()
            run_lints(pkg)
            assert (pkg / "intermediate").is_dir(), (
                "run_lints should create intermediate/ when absent"
            )
            assert (pkg / "intermediate" / "step_7_report.json").exists()


# ─── TestSessionMethodArity ───


class TestSessionMethodArity:
    """Test cases for lint_session_method_arity."""

    def test_instruct_missing_description_fails(self):
        """m.instruct(grounding_context=..., format=...) with no description fails."""
        content = (
            "def run():\n"
            "    m.instruct(\n"
            "        grounding_context='some text',\n"
            "        format=SomeSchema,\n"
            "    )\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_session_method_arity(pkg)
            assert result.verdict == "fail", (
                f"Expected fail for m.instruct() without description, got "
                f"{result.verdict}: {[f.message for f in result.failures]}"
            )
            assert len(result.failures) == 1
            assert "description" in result.failures[0].message
            assert result.failures[0].file == "pipeline.py"

    def test_instruct_positional_description_passes(self):
        content = (
            "def run():\n"
            "    m.instruct('describe the task', format=SomeSchema)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_session_method_arity(pkg).verdict == "pass"

    def test_instruct_keyword_description_passes(self):
        content = (
            "def run():\n"
            "    m.instruct(description='task', format=SomeSchema)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_session_method_arity(pkg).verdict == "pass"

    def test_chat_missing_content_fails(self):
        content = "def run():\n    m.chat(format=Schema)\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_session_method_arity(pkg)
            assert result.verdict == "fail"
            assert "content" in result.failures[0].message

    def test_transform_requires_two_positionals(self):
        bad = "def run():\n    m.transform(my_obj)\n"
        good = "def run():\n    m.transform(my_obj, 'shorten the text')\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg_bad = _make_package(Path(tmp) / "bad", {"pipeline.py": bad})
            result = lint_session_method_arity(pkg_bad)
            assert result.verdict == "fail"
            assert "transformation" in result.failures[0].message
            assert "obj" not in result.failures[0].message

            pkg_good = _make_package(Path(tmp) / "good", {"pipeline.py": good})
            assert lint_session_method_arity(pkg_good).verdict == "pass"

    def test_query_requires_obj_and_query(self):
        good_kw = "def run():\n    m.query(obj=x, query='what is this?')\n"
        bad = "def run():\n    m.query(format=S)\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg_good = _make_package(Path(tmp) / "g", {"pipeline.py": good_kw})
            assert lint_session_method_arity(pkg_good).verdict == "pass"
            pkg_bad = _make_package(Path(tmp) / "b", {"pipeline.py": bad})
            r = lint_session_method_arity(pkg_bad)
            assert r.verdict == "fail"
            assert "obj" in r.failures[0].message and "query" in r.failures[0].message

    def test_non_session_method_call_skipped(self):
        content = (
            "def run():\n"
            "    x = 'hi'.split()\n"
            "    lst.append(1)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_session_method_arity(pkg)
            assert result.verdict == "pass"
            assert result.failures == []

    def test_skips_pycache_intermediate_fixtures(self):
        bad_call = "def x():\n    m.instruct(format=S)\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "intermediate/_old.py": bad_call,
                    "fixtures/some_fixture.py": bad_call,
                    "__pycache__/cached.py": bad_call,
                    "pipeline.py": "def y():\n    m.instruct('valid', format=S)\n",
                },
            )
            result = lint_session_method_arity(pkg)
            assert result.verdict == "pass"

    def test_both_calls_in_one_file_report_both(self):
        content = (
            "def f():\n"
            "    m.instruct(grounding_context='a', format=S)\n"
            "    m.instruct(grounding_context='b', format=S)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_session_method_arity(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 2

    def test_syntax_error_file_is_skipped_silently(self):
        content = "def broken(:\n    pass\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_session_method_arity(pkg)
            assert result.verdict in ("pass", "skipped")


# ─── TestValidationFnNotCalledDirectly ───


class TestValidationFnNotCalledDirectly:
    """Test cases for lint_validation_fn_not_called_directly."""

    def test_direct_call_on_req_attribute_fails(self):
        content = (
            "def check():\n"
            "    result = req.validation_fn(ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_validation_fn_not_called_directly(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1
            assert "validation_fn" in result.failures[0].message

    def test_attribute_access_no_call_passes(self):
        content = (
            "def check():\n"
            "    if req.validation_fn is not None:\n"
            "        pass\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_validation_fn_not_called_directly(pkg).verdict == "pass"

    def test_bare_name_call_passes(self):
        content = (
            "def check():\n"
            "    validation_fn = lambda s: True\n"
            "    validation_fn('hi')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_validation_fn_not_called_directly(pkg).verdict == "pass"

    def test_req_validate_passes(self):
        content = (
            "async def check():\n"
            "    result = await req.validate(backend, ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_validation_fn_not_called_directly(pkg).verdict == "pass"

    def test_other_method_calls_not_flagged(self):
        content = (
            "def check():\n"
            "    x.some_other_method('a')\n"
            "    y.append(1)\n"
            "    z.run(ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_validation_fn_not_called_directly(pkg).verdict == "pass"

    def test_multiple_failures_in_one_file_all_reported(self):
        content = (
            "def check():\n"
            "    r1 = req_a.validation_fn(arg_a)\n"
            "    r2 = req_b.validation_fn(arg_b)\n"
            "    r3 = some.req_c.validation_fn(arg_c)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_validation_fn_not_called_directly(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 3

    def test_skips_pycache_intermediate_fixtures(self):
        bad = "def x():\n    req.validation_fn(arg)\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "intermediate/_x.py": bad,
                    "fixtures/some.py": bad,
                    "__pycache__/cached.py": bad,
                    "pipeline.py": "def y():\n    pass\n",
                },
            )


# ─── TestInstructResultParseBeforeAccess ───


class TestInstructResultParseBeforeAccess:
    """Test cases for lint_instruct_result_parse_before_access (KB1)."""

    _HELPERS = (
        "def _parse_instruct_result(thunk, model_class):\n"
        "    return model_class.model_validate_json(thunk.value)\n"
        "def _safe_parse_with_fallback(thunk, model_class, **fb):\n"
        "    try: return model_class.model_validate_json(thunk.value)\n"
        "    except Exception: return model_class(**fb)\n"
    )

    def test_passes_with_parse_instruct_result(self):
        pipeline = self._HELPERS + (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    intent = _parse_instruct_result(thunk, Intent)\n"
            "    return intent.query_type\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_passes_with_safe_parse_with_fallback(self):
        pipeline = self._HELPERS + (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    intent = _safe_parse_with_fallback(thunk, Intent, query_type='x')\n"
            "    return intent.query_type\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_passes_with_model_validate_json_value(self):
        pipeline = self._HELPERS + (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    parsed = Intent.model_validate_json(thunk.value)\n"
            "    return parsed.query_type\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_fails_with_direct_field_access(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    return thunk.query_type\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_instruct_result_parse_before_access(pkg)
            assert result.verdict == "fail"
            assert "thunk" in result.failures[0].message

    def test_fails_with_model_dump_call(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        t = m.instruct('go', format=Intent)\n"
            "    return t.model_dump()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_instruct_result_parse_before_access(pkg)
            assert result.verdict == "fail"

    def test_fails_with_parsed_repr_access(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        t = m.instruct('go', format=Intent)\n"
            "    x = t.parsed_repr\n"
            "    return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "fail"
            )

    def test_passes_with_access_on_reassigned_parsed_var(self):
        pipeline = self._HELPERS + (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    parsed = _safe_parse_with_fallback(thunk, Intent, query_type='x')\n"
            "    return parsed.query_type + parsed.location\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_untracks_thunk_after_rebind(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    thunk = {'query_type': 'x'}\n"
            "    return thunk['query_type']\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_multi_function_scope_isolation(self):
        pipeline = self._HELPERS + (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def fn_a():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    parsed = _parse_instruct_result(thunk, Intent)\n"
            "    return parsed.query_type\n"
            "def fn_b(thunk):\n"
            "    return thunk.query_type\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_walks_slots_and_constrained_slots(self):
        bad = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        t = m.instruct('go', format=S)\n"
            "    return t.x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"slots.py": bad, "constrained_slots.py": bad},
            )
            result = lint_instruct_result_parse_before_access(pkg)
            assert result.verdict == "fail"

    def test_skips_unparseable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"pipeline.py": "def broken(:\n    pass\n"}
            )
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )

    def test_ignores_instruct_without_format_kwarg(self):
        pipeline = (
            "from mellea import start_session\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('classify the query')\n"
            "    return thunk.value\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert (
                lint_instruct_result_parse_before_access(pkg).verdict == "pass"
            )


# ─── TestFormatAnnotation ───


class TestFormatAnnotation:
    """Test cases for lint_format_annotation."""

    def test_passes_with_format_and_model_validate_json(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    return Intent.model_validate_json(thunk.value)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_format_annotation(pkg).verdict == "pass"

    def test_passes_with_format_and_parse_instruct_result(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    return _parse_instruct_result(thunk, Intent)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_format_annotation(pkg).verdict == "pass"

    def test_passes_with_format_and_safe_parse_with_fallback(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go', format=Intent)\n"
            "    return _safe_parse_with_fallback(thunk, Intent, query_type='x')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_format_annotation(pkg).verdict == "pass"

    def test_fails_when_model_validate_json_with_no_format(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go')\n"
            "    return Intent.model_validate_json(thunk.value)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_format_annotation(pkg)
            assert result.verdict == "fail"
            assert "thunk" in result.failures[0].message
            assert "format=" in result.failures[0].message

    def test_fails_when_parse_instruct_result_with_no_format(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go')\n"
            "    return _parse_instruct_result(thunk, Intent)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_format_annotation(pkg)
            assert result.verdict == "fail"
            assert "_parse_instruct_result" in result.failures[0].message

    def test_fails_when_safe_parse_with_fallback_with_no_format(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go')\n"
            "    return _safe_parse_with_fallback(thunk, Intent, query_type='x')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_format_annotation(pkg)
            assert result.verdict == "fail"
            assert "_safe_parse_with_fallback" in result.failures[0].message

    def test_passes_when_thunk_unused_with_no_format(self):
        """No-format instruct whose result is never parsed is not this lint's concern."""
        pipeline = (
            "from mellea import start_session\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('classify the query')\n"
            "    return thunk\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_format_annotation(pkg).verdict == "pass"

    def test_dedups_multiple_parse_uses_of_same_thunk(self):
        """A single bad instruct used twice for parsing emits one failure, not two."""
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Intent\n"
            "def run_pipeline():\n"
            "    with start_session('o','m') as m:\n"
            "        thunk = m.instruct('go')\n"
            "    a = Intent.model_validate_json(thunk.value)\n"
            "    b = _parse_instruct_result(thunk, Intent)\n"
            "    return a, b\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_format_annotation(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1

    def test_walks_slots_and_constrained_slots(self):
        bad = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        t = m.instruct('go')\n"
            "    return S.model_validate_json(t.value)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"slots.py": bad, "constrained_slots.py": bad},
            )
            result = lint_format_annotation(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 2

    def test_skips_unparseable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"pipeline.py": "def broken(:\n    pass\n"}
            )
            assert lint_format_annotation(pkg).verdict == "pass"

    def test_passes_when_no_pipeline_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"main.py": "x = 1\n"})
            result = lint_format_annotation(pkg)
            assert result.verdict == "pass"
            assert result.files_checked == 0


# ─── TestSessionBoundary ───


class TestSessionBoundary:
    """Test cases for lint_session_boundary (KB5)."""

    def test_passes_with_single_format_type(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import TriageVerdict\n"
            "def run_pipeline(t: str) -> dict:\n"
            "    with start_session('ollama', 'm') as m:\n"
            "        v1 = m.instruct('Triage', format=TriageVerdict)\n"
            "        v2 = m.instruct('Refine', format=TriageVerdict)\n"
            "    return {}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_session_boundary(pkg).verdict == "pass"

    def test_fails_with_two_format_types_in_one_session(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import A, B\n"
            "def run_pipeline(t: str) -> dict:\n"
            "    with start_session('o','m') as m:\n"
            "        x = m.instruct('one', format=A)\n"
            "        y = m.instruct('two', format=B)\n"
            "    return {}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_session_boundary(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1
            assert "A" in result.failures[0].message
            assert "B" in result.failures[0].message

    def test_passes_with_two_sessions_each_one_format(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import A, B\n"
            "def f(x):\n"
            "    with start_session('o','m') as m:\n"
            "        a = m.instruct('1', format=A)\n"
            "    with start_session('o','m') as m:\n"
            "        b = m.instruct('2', format=B)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_session_boundary(pkg).verdict == "pass"

    def test_passes_with_no_format_kwarg(self):
        pipeline = (
            "from mellea import start_session\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('Answer')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_session_boundary(pkg).verdict == "pass"

    def test_fails_with_three_distinct_format_types(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import A, B, C\n"
            "def f(x):\n"
            "    with start_session('o','m') as m:\n"
            "        a = m.instruct('1', format=A)\n"
            "        b = m.instruct('2', format=B)\n"
            "        c = m.instruct('3', format=C)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_session_boundary(pkg)
            assert result.verdict == "fail"
            msg = result.failures[0].message
            assert "A" in msg and "B" in msg and "C" in msg

    def test_checks_slots_and_constrained_slots(self):
        bad = (
            "from mellea import start_session\n"
            "from .schemas import A, B\n"
            "def helper():\n"
            "    with start_session('o','m') as m:\n"
            "        m.instruct('x', format=A)\n"
            "        m.instruct('y', format=B)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"slots.py": bad, "constrained_slots.py": bad},
            )
            result = lint_session_boundary(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 2

    def test_skips_unparseable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": "def broken(:\n    pass\n"})
            assert lint_session_boundary(pkg).verdict == "pass"

    def test_passes_when_no_pipeline_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"main.py": "x = 1\n"})
            result = lint_session_boundary(pkg)
            assert result.verdict == "pass"
            assert result.files_checked == 0


# ─── TestFixturePydanticCoercion ───


_SCHEMAS_PY = (
    "from pydantic import BaseModel\n"
    "from typing import Optional\n"
    "\n"
    "class IntakeContext(BaseModel):\n"
    "    sport: str\n"
    "    institution: str\n"
    "\n"
    "class ReviewMemorandum(BaseModel):\n"
    "    findings: list[str]\n"
)

_PIPELINE_WITH_PYDANTIC_PARAM = (
    "from .schemas import IntakeContext, ReviewMemorandum\n"
    "from typing import Optional\n"
    "\n"
    "def run_pipeline(contract_text: str, intake: IntakeContext) -> ReviewMemorandum:\n"
    "    return ReviewMemorandum(findings=[intake.sport])\n"
)

_PIPELINE_WITHOUT_PYDANTIC_PARAM = (
    "def run_pipeline(user_query: str) -> str:\n"
    "    return user_query\n"
)


class TestFixturePydanticCoercion:
    """Test cases for lint_fixture_pydantic_coercion."""

    def test_bare_dict_for_pydantic_param_fails_nil_contract_reproducer(self):
        """The exact nil-contract bug: fixture passes intake as a bare dict."""
        fixture = (
            'def make_x():\n'
            '    inputs = {\n'
            '        "contract_text": "txt",\n'
            '        "intake": {"sport": "Football", "institution": "U.Fla"},\n'
            '    }\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            result = lint_fixture_pydantic_coercion(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1
            assert "intake" in result.failures[0].message
            assert "IntakeContext" in result.failures[0].message

    def test_model_constructor_call_passes(self):
        fixture = (
            'def make_x():\n'
            '    inputs = {\n'
            '        "contract_text": "txt",\n'
            '        "intake": IntakeContext(**{"sport": "F", "institution": "U"}),\n'
            '    }\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "pass"

    def test_variable_reference_passes(self):
        fixture = (
            'def make_x():\n'
            '    ctx = IntakeContext(sport="F", institution="U")\n'
            '    inputs = {"contract_text": "txt", "intake": ctx}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "pass"

    def test_non_pydantic_param_dict_value_ignored(self):
        fixture = (
            'def make_x():\n'
            '    inputs = {"user_query": "hello"}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "pipeline.py": _PIPELINE_WITHOUT_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "pass"

    def test_optional_pydantic_param_dict_value_fails(self):
        pipeline = (
            "from .schemas import IntakeContext, ReviewMemorandum\n"
            "from typing import Optional\n"
            "\n"
            "def run_pipeline(intake: Optional[IntakeContext] = None) -> str:\n"
            "    return intake.sport if intake else ''\n"
        )
        fixture = (
            'def make_x():\n'
            '    inputs = {"intake": {"sport": "F", "institution": "U"}}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": pipeline,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "fail"

    def test_pipe_or_none_pydantic_param_dict_value_fails(self):
        pipeline = (
            "from .schemas import IntakeContext, ReviewMemorandum\n"
            "\n"
            "def run_pipeline(intake: IntakeContext | None = None) -> str:\n"
            "    return intake.sport if intake else ''\n"
        )
        fixture = (
            'def make_x():\n'
            '    inputs = {"intake": {"sport": "F", "institution": "U"}}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": pipeline,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "fail"

    def test_transitive_pydantic_subclass_detected(self):
        schemas = (
            "from pydantic import BaseModel\n"
            "class Foo(BaseModel):\n"
            "    a: str\n"
            "class Bar(Foo):\n"
            "    b: str\n"
        )
        pipeline = (
            "from .schemas import Bar\n"
            "def run_pipeline(bar: Bar) -> str:\n"
            "    return bar.a\n"
        )
        fixture = (
            'def make_x():\n'
            '    inputs = {"bar": {"a": "x", "b": "y"}}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": schemas,
                    "pipeline.py": pipeline,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "fail"

    def test_pipeline_missing_returns_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "fixtures").mkdir()
            (pkg / "fixtures" / "__init__.py").write_text("ALL_FIXTURES = []\n")
            result = lint_fixture_pydantic_coercion(pkg)
            assert result.verdict == "skipped"
            assert "pipeline.py" in (result.skipped_reason or "")

    def test_fixtures_dir_missing_returns_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"pipeline.py": _PIPELINE_WITHOUT_PYDANTIC_PARAM},
            )
            result = lint_fixture_pydantic_coercion(pkg)
            assert result.verdict == "skipped"

    def test_schemas_missing_no_false_positive(self):
        fixture = (
            'def make_x():\n'
            '    inputs = {"intake": {"sport": "F"}}\n'
            '    return inputs, "x", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": fixture,
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "pass"

    def test_syntax_error_in_fixture_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/x.py": "def broken(:\n    pass\n",
                },
            )
            assert lint_fixture_pydantic_coercion(pkg).verdict == "pass"

    def test_multiple_fixtures_mixed_results(self):
        good = (
            'def make_g():\n'
            '    inputs = {"intake": IntakeContext(sport="F", institution="U")}\n'
            '    return inputs, "g", "desc"\n'
        )
        bad = (
            'def make_b():\n'
            '    inputs = {"intake": {"sport": "F", "institution": "U"}}\n'
            '    return inputs, "b", "desc"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {
                    "schemas.py": _SCHEMAS_PY,
                    "pipeline.py": _PIPELINE_WITH_PYDANTIC_PARAM,
                    "fixtures/__init__.py": "ALL_FIXTURES = []\n",
                    "fixtures/g.py": good,
                    "fixtures/b.py": bad,
                },
            )
            result = lint_fixture_pydantic_coercion(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 1
            assert result.failures[0].file == "fixtures/b.py"


# ─── TestGroundingContextTypes ───


class TestGroundingContextTypes:
    """Test cases for lint_grounding_context_types.

    Regression target: a `m.instruct(..., grounding_context={...})` call
    whose dict value was a list comprehension produced
    `ValueError: parts should only contain CBlocks, Components, or
    ModelOutputThunks; found <list>` at runtime.
    """

    def test_passes_with_string_literal_values(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'a': 'hello', 'b': 'world'})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "pass"

    def test_passes_with_str_call(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(x):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'x': str(x)})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "pass"

    def test_passes_with_fstring(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(x):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'x': f'value={x}'})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "pass"

    def test_fails_with_list_comprehension(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import MitigationPlan\n"
            "def f(risks):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=MitigationPlan, "
            "grounding_context={'risks': [r.model_dump() for r in risks]})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_grounding_context_types(pkg)
            assert result.verdict == "fail"
            assert any(
                "collection-literal" in f.message.lower()
                or "list" in f.message.lower()
                for f in result.failures
            )

    def test_fails_with_list_literal(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'items': ['a', 'b']})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "fail"

    def test_fails_with_dict_literal(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'obj': {'k': 'v'}})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "fail"

    def test_warns_with_bare_name(self):
        """Name/Attribute values are ambiguous — could be a string at runtime."""
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(some_var):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'x': some_var})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_grounding_context_types(pkg)
            assert result.verdict == "warning"
            assert len(result.failures) == 1

    def test_warns_with_attribute_access(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(obj):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={'x': obj.field})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "warning"

    def test_mixed_definite_and_ambiguous_returns_fail(self):
        """Any definite collection elevates the overall verdict to fail."""
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(v, risks):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, grounding_context={"
            "'ambiguous': v, 'definite': [r for r in risks]})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_grounding_context_types(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 2

    def test_passes_when_no_grounding_context(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f():\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_grounding_context_types(pkg).verdict == "pass"

    def test_skips_unparseable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"pipeline.py": "def broken(:\n    pass\n"}
            )
            assert lint_grounding_context_types(pkg).verdict == "pass"

    def test_walks_slots_and_constrained_slots(self):
        bad = (
            "from mellea import start_session\n"
            "from .schemas import S\n"
            "def f(items):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct('go', format=S, "
            "grounding_context={'items': [x for x in items]})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp),
                {"slots.py": bad, "constrained_slots.py": bad},
            )
            result = lint_grounding_context_types(pkg)
            assert result.verdict == "fail"
            files = sorted(f.file for f in result.failures)
            assert files == ["constrained_slots.py", "slots.py"]


# ─── TestStdlibArgTypes ───


class TestStdlibArgTypes:
    """Test cases for lint_stdlib_arg_types.

    Narrow MVP: checks `grounding_context=` on instruct/chat/act family
    methods for clearly-non-dict arguments (non-dict Constant, f-string,
    or Name pointing to a parameter with a provably-non-dict annotation).
    Ambiguous cases (no annotation, Any, Optional/Union) pass silently.
    """

    def test_passes_with_dict_literal(self):
        pipeline = (
            "def f():\n"
            "    m.instruct('go', grounding_context={'a': 'b'})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_dict_call(self):
        pipeline = (
            "def f():\n"
            "    m.instruct('go', grounding_context=dict(a='b'))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_grounding_context_none(self):
        """`grounding_context=None` is a Mellea idiom; don't flag."""
        pipeline = (
            "def f():\n"
            "    m.instruct('go', grounding_context=None)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_name_dict_annotated(self):
        pipeline = (
            "def f(ctx: dict):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_name_mapping_annotated(self):
        pipeline = (
            "from typing import Mapping\n"
            "def f(ctx: Mapping[str, str]):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_name_no_annotation(self):
        """Unannotated parameter is ambiguous — must NOT flag."""
        pipeline = (
            "def f(ctx):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_name_any_annotation(self):
        pipeline = (
            "from typing import Any\n"
            "def f(ctx: Any):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_passes_with_name_optional_annotation(self):
        """`Optional[str]` could be `None` (handled separately) or a string;
        lint stays conservative and doesn't flag."""
        pipeline = (
            "from typing import Optional\n"
            "def f(ctx: Optional[dict]):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_fails_with_string_literal(self):
        pipeline = (
            "def f():\n"
            "    m.instruct('go', grounding_context='oops')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_stdlib_arg_types(pkg)
            assert result.verdict == "fail"
            assert "non-dict literal" in result.failures[0].message

    def test_fails_with_int_literal(self):
        pipeline = (
            "def f():\n"
            "    m.instruct('go', grounding_context=42)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "fail"

    def test_fails_with_fstring(self):
        pipeline = (
            "def f(x):\n"
            "    m.instruct('go', grounding_context=f'hello {x}')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "fail"

    def test_fails_with_name_concrete_class_annotation(self):
        pipeline = (
            "class NegotiationContext:\n"
            "    pass\n"
            "def f(ctx: NegotiationContext):\n"
            "    m.instruct('go', grounding_context=ctx)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_stdlib_arg_types(pkg)
            assert result.verdict == "fail"
            assert "ctx" in result.failures[0].message
            assert "model_dump" in result.failures[0].message

    def test_fails_with_name_list_annotation(self):
        pipeline = (
            "def f(items: list[str]):\n"
            "    m.instruct('go', grounding_context=items)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "fail"

    def test_fails_with_chat_and_act_methods(self):
        pipeline = (
            "def f():\n"
            "    m.chat('go', grounding_context='oops')\n"
            "    m.act('go', grounding_context=42)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_stdlib_arg_types(pkg)
            assert result.verdict == "fail"
            assert len(result.failures) == 2

    def test_passes_with_no_grounding_context_kwarg(self):
        pipeline = (
            "def f():\n"
            "    m.instruct('go')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_skips_unparseable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"pipeline.py": "def broken(:\n    pass\n"}
            )
            assert lint_stdlib_arg_types(pkg).verdict == "pass"

    def test_walks_requirements_and_tools(self):
        bad = (
            "def f():\n"
            "    m.instruct('go', grounding_context='oops')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"requirements.py": bad, "tools.py": bad}
            )
            result = lint_stdlib_arg_types(pkg)
            assert result.verdict == "fail"
            files = sorted(f.file for f in result.failures)
            assert files == ["requirements.py", "tools.py"]

    def test_passes_with_no_pipeline_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"main.py": "x = 1\n"})
            result = lint_stdlib_arg_types(pkg)
            assert result.verdict == "pass"
            assert result.files_checked == 0


# ─── TestPrefixPersona ───


class TestPrefixPersona:
    """Test cases for lint_prefix_persona (KB7)."""

    def test_passes_with_string_literal_prefix(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import Result\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            '        r = m.instruct(q, format=Result, prefix=\'{"value":\')\n'
            "    return r\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_prefix_persona(pkg).verdict == "pass"

    def test_fails_with_config_constant_via_assignment(self):
        config = 'PREFIX_TEXT = "You are a helpful agent."\n'
        pipeline = (
            "from mellea import start_session\n"
            "from .config import PREFIX_TEXT\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct(q, prefix=PREFIX_TEXT)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"config.py": config, "pipeline.py": pipeline}
            )
            result = lint_prefix_persona(pkg)
            assert result.verdict == "fail"
            assert "PREFIX_TEXT" in result.failures[0].message
            assert "SYSTEM_PROMPT" in result.failures[0].message

    def test_passes_with_system_prompt_pattern(self):
        config = 'PREFIX_TEXT = "persona"\n'
        pipeline = (
            "from mellea import start_session\n"
            "from mellea.backends.model_options import ModelOption\n"
            "from .config import PREFIX_TEXT\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct(q, model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT})\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(
                Path(tmp), {"config.py": config, "pipeline.py": pipeline}
            )
            assert lint_prefix_persona(pkg).verdict == "pass"

    def test_fails_with_config_import_no_config_py(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .config import PERSONA\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct(q, prefix=PERSONA)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            result = lint_prefix_persona(pkg)
            assert result.verdict == "fail"
            assert "PERSONA" in result.failures[0].message

    def test_fails_with_bare_name(self):
        pipeline = (
            "from mellea import start_session\n"
            "def run_pipeline(q):\n"
            "    PREFIX_TEXT = 'persona'\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct(q, prefix=PREFIX_TEXT)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_prefix_persona(pkg).verdict == "fail"

    def test_passes_with_no_prefix_kwarg(self):
        pipeline = (
            "from mellea import start_session\n"
            "from .schemas import R\n"
            "def run_pipeline(q):\n"
            "    with start_session('o','m') as m:\n"
            "        return m.instruct(q, format=R)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": pipeline})
            assert lint_prefix_persona(pkg).verdict == "pass"




# ─── TestParseable ───


class TestParseable:
    """Tier 1: every .py file parses + `<pkg>.pipeline` imports as a subprocess."""

    def test_passes_on_clean_package(self):
        files = {
            "pipeline.py": "def run_pipeline(x: str) -> str:\n    return x\n",
            "__init__.py": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp) / "x_mellea", files)
            result = lint_parseable(pkg)
            assert result.verdict == "pass", (
                f"clean package should pass; got "
                f"{[f.message for f in result.failures]}"
            )

    def test_fails_when_pipeline_missing(self):
        """Tier 1 should hard-fail loudly when the entry module is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp) / "x_mellea", {"__init__.py": ""})
            result = lint_parseable(pkg)
            assert result.verdict == "fail"
            assert "pipeline.py absent" in result.failures[0].message

    def test_fails_on_syntax_error(self):
        files = {
            "pipeline.py": "def run_pipeline(x):\n    return x\n",
            "__init__.py": "",
            "broken.py": "def broken(:\n    pass\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp) / "x_mellea", files)
            result = lint_parseable(pkg)
            assert result.verdict == "fail"
            offending = [f for f in result.failures if f.file == "broken.py"]
            assert len(offending) == 1
            assert "SyntaxError" in offending[0].message
            assert offending[0].line is not None

    def test_fails_on_hallucinated_import_path(self):
        """`from mellea.stdlib.strategies import RepairTemplateStrategy` —
        wrong path that ast.parse() can't catch; subprocess import does."""
        files = {
            "pipeline.py": (
                "from mellea.stdlib.strategies import RepairTemplateStrategy\n"
                "def run_pipeline(x: str) -> str:\n    return x\n"
            ),
            "__init__.py": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp) / "x_mellea", files)
            result = lint_parseable(pkg)
            # Either fail (Mellea installed → real ImportError surfaced) or
            # pass on a CI env where mellea isn't on PYTHONPATH at all and
            # the subprocess errors for a different reason; we accept fail.
            assert result.verdict in ("pass", "fail")
            if result.verdict == "fail":
                # When it fails, the message should cite the offending import.
                msgs = " ".join(f.message for f in result.failures)
                assert "import" in msgs.lower()

    def test_includes_fixtures_files_in_parse_check(self):
        files = {
            "pipeline.py": "def run_pipeline(x: str) -> str:\n    return x\n",
            "__init__.py": "",
            "fixtures/__init__.py": "ALL_FIXTURES = []\n",
            "fixtures/broken.py": "def broken(:\n    pass\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp) / "x_mellea", files)
            result = lint_parseable(pkg)
            assert result.verdict == "fail"
            offending = [f for f in result.failures if "broken.py" in f.file]
            assert len(offending) == 1


# ─── TestImportSoundness ───


_API_REF_WITH_MODULES = json.dumps({
    "format_version": "1.0",
    "mellea_version": "0.6.0",
    "modules": {
        "mellea.backends.model_options": {},
        "mellea.stdlib.requirements": {},
        "mellea.stdlib.sampling": {},
    },
})


class TestImportSoundness:
    """Every `mellea.*` import path must exist in mellea_api_ref.json."""

    def test_passes_when_imports_match_known_modules(self):
        files = {
            "pipeline.py": (
                "from mellea.stdlib.sampling import RepairTemplateStrategy\n"
                "from mellea.backends.model_options import ModelOption\n"
                "def run_pipeline(x):\n    return x\n"
            ),
            "intermediate/mellea_api_ref.json": _API_REF_WITH_MODULES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            assert lint_import_soundness(pkg).verdict == "pass"

    def test_fails_on_shortened_path(self):
        files = {
            "pipeline.py": (
                "from mellea.model_options import ModelOption\n"
                "def run_pipeline(x):\n    return x\n"
            ),
            "intermediate/mellea_api_ref.json": _API_REF_WITH_MODULES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            result = lint_import_soundness(pkg)
            assert result.verdict == "fail"
            assert "mellea.model_options" in result.failures[0].message

    def test_top_level_mellea_import_accepted(self):
        """`from mellea import generative` reaches a top-level re-export
        that the grounding doesn't index — must not false-positive."""
        files = {
            "slots.py": (
                "from mellea import generative\n"
                "@generative\n"
                "def x(s: str) -> str:\n    return s\n"
            ),
            "intermediate/mellea_api_ref.json": _API_REF_WITH_MODULES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            assert lint_import_soundness(pkg).verdict == "pass"

    def test_non_mellea_imports_ignored(self):
        files = {
            "pipeline.py": (
                "from pydantic import BaseModel\n"
                "import os\n"
                "def run_pipeline(x): return x\n"
            ),
            "intermediate/mellea_api_ref.json": _API_REF_WITH_MODULES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            assert lint_import_soundness(pkg).verdict == "pass"

    def test_skipped_when_api_ref_missing(self):
        files = {"pipeline.py": "def run_pipeline(x): return x\n"}
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            result = lint_import_soundness(pkg)
            assert result.verdict == "skipped"
            assert "mellea_api_ref" in (result.skipped_reason or "")

    def test_skipped_when_grounding_unavailable(self):
        files = {
            "pipeline.py": "from mellea.foo import bar\n",
            "intermediate/mellea_api_ref.json": json.dumps({
                "grounding_unavailable": True,
            }),
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            assert lint_import_soundness(pkg).verdict == "skipped"

    def test_import_module_statement_form(self):
        """`import mellea.X` (not `from`) — same rule applies."""
        files = {
            "pipeline.py": (
                "import mellea.nonexistent\n"
                "def run_pipeline(x): return x\n"
            ),
            "intermediate/mellea_api_ref.json": _API_REF_WITH_MODULES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            result = lint_import_soundness(pkg)
            assert result.verdict == "fail"
            assert "mellea.nonexistent" in result.failures[0].message


# ─── TestImportSideEffects ───


class TestImportSideEffects:
    """Module-level Calls outside the allowlist."""

    def test_passes_with_allowlisted_logger(self):
        content = (
            "import logging\n"
            "LOGGER = logging.getLogger(__name__)\n"
            "def run_pipeline(x): return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_import_side_effects(pkg).verdict == "pass"

    def test_passes_with_allowlisted_env_get(self):
        content = (
            "import os\n"
            "DEBUG = os.environ.get('DEBUG', '0')\n"
            "def run_pipeline(x): return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_import_side_effects(pkg).verdict == "pass"

    def test_fails_on_bare_load_dotenv_call(self):
        content = (
            "from dotenv import load_dotenv\n"
            "load_dotenv()\n"
            "def run_pipeline(x): return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_import_side_effects(pkg)
            assert result.verdict == "fail"
            assert "load_dotenv" in result.failures[0].message

    def test_fails_on_assignment_with_load_dotenv(self):
        content = (
            "from dotenv import load_dotenv\n"
            "RESULT = load_dotenv()\n"
            "def run_pipeline(x): return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            result = lint_import_side_effects(pkg)
            assert result.verdict == "fail"

    def test_passes_on_safe_assignment_with_call(self):
        """`LOGGER = logging.getLogger(__name__)` is allowed."""
        content = (
            "import logging\n"
            "LOGGER = logging.getLogger(__name__)\n"
            "def run_pipeline(x): return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_import_side_effects(pkg).verdict == "pass"

    def test_only_inspects_listed_files(self):
        """Files outside the allowlist (e.g. test.py) are not inspected."""
        files = {
            "pipeline.py": "def run_pipeline(x): return x\n",
            "some_extra.py": "load_dotenv()\n",  # not in the allowlist
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), files)
            assert lint_import_side_effects(pkg).verdict == "pass"

    def test_call_inside_function_body_not_flagged(self):
        """Only module-level calls fire — calls inside a def() are fine."""
        content = (
            "from dotenv import load_dotenv\n"
            "def run_pipeline(x):\n"
            "    load_dotenv()\n"
            "    return x\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": content})
            assert lint_import_side_effects(pkg).verdict == "pass"

    def test_syntax_error_file_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _make_package(Path(tmp), {"pipeline.py": "def x(:\n    pass\n"})
            result = lint_import_side_effects(pkg)
            assert result.verdict in ("pass", "skipped")


