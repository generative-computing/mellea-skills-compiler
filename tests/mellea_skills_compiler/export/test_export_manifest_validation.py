"""Unit tests for export manifest validation in exporter.py."""

import json
import pytest

from mellea_skills_compiler.export.exporter import (
    Invocation,
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
