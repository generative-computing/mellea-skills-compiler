import importlib
import os
import sys

import pytest

import mellea_skills_compiler
import mellea_skills_compiler.inference  # noqa: F401

_INFERENCE = "mellea_skills_compiler.inference"


@pytest.fixture
def reload_inference(monkeypatch):
    """Return a reloader whose side effects monkeypatch undoes at teardown."""
    # setenv before delenv so an unset var is recorded and removed again.
    for var in ("OLLAMA_HOST", "OLLAMA_API_URL"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.delitem(sys.modules, _INFERENCE)
    monkeypatch.delattr(mellea_skills_compiler, "inference")

    def _reload():
        importlib.reload(mellea_skills_compiler)
        return importlib.import_module(_INFERENCE)

    return _reload


def test_api_url_propagates_to_ollama_host(monkeypatch, reload_inference):
    monkeypatch.setenv("OLLAMA_API_URL", "http://127.0.0.1:9")
    mod = reload_inference()
    assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:9"
    assert mod.OLLAMA_API_URL == "http://127.0.0.1:9"


def test_ollama_host_takes_precedence(monkeypatch, reload_inference):
    monkeypatch.setenv("OLLAMA_HOST", "http://host:1")
    monkeypatch.setenv("OLLAMA_API_URL", "http://other:2")
    mod = reload_inference()
    assert os.environ["OLLAMA_HOST"] == "http://host:1"
    assert mod.OLLAMA_API_URL == "http://host:1"


def test_nothing_set_leaves_host_unset(reload_inference):
    reload_inference()
    assert "OLLAMA_HOST" not in os.environ
