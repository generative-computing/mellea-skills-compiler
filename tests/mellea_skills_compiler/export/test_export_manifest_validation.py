"""Unit tests for export manifest validation in exporter.py."""

import json
import pytest

from mellea_skills_compiler.export.exporter import (
    Invocation,
    _parse_entry_signature,
    _validate_entry_signature_str,
    run_export,
    stage1_validate,
    stage2_load,
)


def _write_pkg(tmp_path, manifest_content):
    pkg = tmp_path / "demo_mellea"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    if isinstance(manifest_content, str):
        (pkg / "melleafy.json").write_text(manifest_content)
    else:
        (pkg / "melleafy.json").write_text(json.dumps(manifest_content))
    return pkg


def test_stage1_validate_rejects_non_object_json(tmp_path, capsys):
    pkg = _write_pkg(tmp_path, '["bad"]')
    inv = Invocation(package_path=pkg, target="pi", out_path=tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        stage1_validate(inv)
    assert exc.value.code == 2
    assert "JSON object" in capsys.readouterr().err


def test_stage1_validate_rejects_non_string_manifest_version(tmp_path, capsys):
    pkg = _write_pkg(
        tmp_path,
        {
            "manifest_version": 1.1,
            "package_name": "demo_mellea",
            "entry_signature": "run_pipeline() -> str",
        },
    )
    inv = Invocation(package_path=pkg, target="pi", out_path=tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        stage1_validate(inv)
    assert exc.value.code == 2
    assert "manifest_version" in capsys.readouterr().err


def test_stage2_load_rejects_malformed_entry_signature(tmp_path, capsys):
    pkg = _write_pkg(
        tmp_path,
        {
            "manifest_version": "1.1.0",
            "package_name": "demo_mellea",
            "entry_signature": "<populated in Step 6>",
        },
    )
    inv = Invocation(package_path=pkg, target="pi", out_path=tmp_path / "out")
    manifest = stage1_validate(inv)
    with pytest.raises(SystemExit) as exc:
        stage2_load(inv, manifest)
    assert exc.value.code == 2
    assert "malformed" in capsys.readouterr().err


def test_stage2_load_rejects_non_identifier_package_name(tmp_path, capsys):
    pkg = _write_pkg(
        tmp_path,
        {
            "manifest_version": "1.1.0",
            "package_name": "bad-name",
            "entry_signature": "run_pipeline() -> str",
        },
    )
    inv = Invocation(package_path=pkg, target="pi", out_path=tmp_path / "out")
    manifest = stage1_validate(inv)
    with pytest.raises(SystemExit) as exc:
        stage2_load(inv, manifest)
    assert exc.value.code == 2
    assert "identifier" in capsys.readouterr().err


def test_run_export_reports_invalid_json_when_out_path_omitted(tmp_path, capsys):
    pkg = _write_pkg(tmp_path, "{broken json")
    inv = Invocation(package_path=pkg, target="pi")
    with pytest.raises(SystemExit) as exc:
        run_export(inv)
    assert exc.value.code == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_entry_signature_accepts_parenthesised_defaults_and_quotes(tmp_path):
    sig_tuple = "run_pipeline(q: str, opts: tuple = ()) -> str"
    assert _validate_entry_signature_str(sig_tuple) is None
    parsed_tuple = _parse_entry_signature(sig_tuple)
    assert parsed_tuple.function_name == "run_pipeline"
    assert parsed_tuple.return_type == "str"
    assert parsed_tuple.params == [
        {"name": "q", "type": "str", "required": True, "default": None},
        {"name": "opts", "type": "tuple", "required": False, "default": "()"},
    ]

    sig_complex = (
        "run_pipeline(q: str, coords: tuple[int, int] = (0, 0), "
        'sep: str = ")", mode: Literal["a=b"] = "a=b") -> tuple[str, int]'
    )
    assert _validate_entry_signature_str(sig_complex) is None
    parsed_complex = _parse_entry_signature(sig_complex)
    assert parsed_complex.return_type == "tuple[str, int]"
    assert parsed_complex.params == [
        {"name": "q", "type": "str", "required": True, "default": None},
        {
            "name": "coords",
            "type": "tuple[int, int]",
            "required": False,
            "default": "(0, 0)",
        },
        {"name": "sep", "type": "str", "required": False, "default": '")"'},
        {
            "name": "mode",
            "type": 'Literal["a=b"]',
            "required": False,
            "default": '"a=b"',
        },
    ]

    pkg = _write_pkg(
        tmp_path,
        {
            "manifest_version": "1.1.0",
            "package_name": "demo_mellea",
            "entry_signature": sig_tuple,
        },
    )
    (pkg / "pipeline.py").write_text(
        "def run_pipeline(q: str, opts: tuple = ()) -> str:\n    return q\n"
    )
    (pkg / "config.py").write_text('BACKEND = "ollama"\nMODEL_ID = "granite4.1:3b"\n')
    inv = Invocation(package_path=pkg, target="pi", out_path=tmp_path / "out")
    loaded = stage2_load(inv, stage1_validate(inv))
    assert loaded.sig.params[1]["default"] == "()"


@pytest.mark.parametrize(
    "bad_sig",
    [
        "run_pipeline(q: str, opts: tuple = () -> str",
        "run_pipeline(q: str = ) -> str",
        "run_pipeline(q: str, , b: int) -> str",
        "run_pipeline(, q: str) -> str",
        "run_pipeline(q: str) -> tuple[str, )",
    ],
)
def test_entry_signature_rejects_unbalanced_or_empty_segments(bad_sig):
    assert _validate_entry_signature_str(bad_sig) is not None
