import importlib
import os
import sys


def _reload_inference():
    pkg = importlib.reload(importlib.import_module("mellea_skills_compiler"))
    sys.modules.pop("mellea_skills_compiler.inference", None)
    return importlib.import_module("mellea_skills_compiler.inference")


def test_api_url_propagates_to_ollama_host(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_API_URL", "http://127.0.0.1:9")
    mod = _reload_inference()
    assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:9"
    assert mod.OLLAMA_API_URL == "http://127.0.0.1:9"


def test_ollama_host_takes_precedence(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://host:1")
    monkeypatch.setenv("OLLAMA_API_URL", "http://other:2")
    mod = _reload_inference()
    assert os.environ["OLLAMA_HOST"] == "http://host:1"
    assert mod.OLLAMA_API_URL == "http://host:1"


def test_nothing_set_leaves_host_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_API_URL", raising=False)
    _reload_inference()
    assert "OLLAMA_HOST" not in os.environ
