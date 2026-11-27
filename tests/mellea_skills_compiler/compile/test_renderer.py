import json

import pytest

from mellea_skills_compiler.compile.writers.renderer import render_writers


def test_enforce_fails_on_writer_error(tmp_path):
    emission = tmp_path / "intermediate" / "config_emission.json"
    emission.parent.mkdir()
    emission.write_text(json.dumps({"constants": [{"name": "X", "value": 1}]}))  # no "type"
    with pytest.raises(Exception, match=r"\[writer:config\.py\] writer .* raised"):
        render_writers(tmp_path, enforce=True)
