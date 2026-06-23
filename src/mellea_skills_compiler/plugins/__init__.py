"""Runtime governance hooks for Mellea pipelines."""

from abc import ABC, abstractmethod

from mellea import plugins as mellea_plugins

from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


class BasePlugin(ABC):

    @abstractmethod
    def summary() -> dict:
        raise NotImplementedError

    def register(self):
        """Add plugin to the global registry."""
        mellea_plugins.register(self)

    def deregister(self) -> None:
        """Remove plugin from the global registry."""
        try:
            mellea_plugins.unregister(self)
        except (ImportError, Exception):
            pass
