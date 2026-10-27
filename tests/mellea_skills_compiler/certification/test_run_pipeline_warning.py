"""The run command's missing-manifest warning must not name a CLI-only command."""

from unittest.mock import patch

from mellea_skills_compiler.certification import pipeline
from mellea_skills_compiler.enums import GuardianMode


def test_missing_manifest_warning_names_certify_without_cli_prefix(tmp_path):
    skill_dir = tmp_path / "weather_mellea"
    skill_dir.mkdir()

    with (
        patch.object(pipeline.console, "print") as console_print,
        # Stop right after the manifest check; the pipeline itself is out of scope.
        patch.object(pipeline, "load_skill_pipeline", side_effect=RuntimeError("stop")),
    ):
        pipeline.run_pipeline(skill_dir, GuardianMode.AUDIT, input="x")

    warning = console_print.call_args_list[0].args[0]
    assert "certify" in warning
    assert "mellea-skills ingest" not in warning
    assert "mellea-skills certify" not in warning
