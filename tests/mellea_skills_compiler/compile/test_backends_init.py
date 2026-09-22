"""Tests that all backends are registered correctly."""

from mellea_skills_compiler.compile.backend import global_registry
from mellea_skills_compiler.compile.backends.pi import PiBackend


class TestBackendRegistration:
    def test_pi_backend_registered(self):
        assert "pi" in global_registry.list_backends()

    def test_get_pi_backend_returns_instance(self):
        backend = global_registry.get_backend("pi")
        assert isinstance(backend, PiBackend)

    def test_all_three_backends_registered(self):
        assert global_registry.list_backends() == ["bob", "claude", "pi"]
