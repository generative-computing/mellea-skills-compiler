import importlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Literal, Optional

import mellea_skills_compiler
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


class CompileMetadata:
    """Top-level record written to ``compile_metadata.json`` after a successful compile.

    This is a singleton that must be initialized via ``init()`` before any write methods
    are called. The singleton is reset on each ``init()`` call to support multiple
    compile runs in the same process.

    Usage:
        CompileMetadata.init(mellea_package_dir)
        CompileMetadata.record_args(...)
        CompileMetadata.record_backend(...)
        CompileMetadata.record_melleafy()
        CompileMetadata.record_completion()
    """

    _instance: Optional["CompileMetadata"] = None

    def __init__(self, mellea_package_dir: Path):
        self._mellea_package_dir = mellea_package_dir
        self._metadata: Dict[str, object] = {
            "schema_version": "1.0.0",
            "library_version": mellea_skills_compiler.__version__,
            "started_at": self._get_current_timestamp(),
            "environment": {
                "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
                "python": sys.version.split()[0],
                "mellea": _get_mellea_version(),
            },
            "git": _git_info(),
        }

    @staticmethod
    def _get_current_timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @classmethod
    def _require_init(cls) -> "CompileMetadata":
        """Return the singleton instance or raise if not initialized."""
        if cls._instance is None:
            raise RuntimeError(
                "CompileMetadata.init() must be called before any write methods"
            )
        return cls._instance

    @classmethod
    def init(cls, mellea_package_dir: Path) -> None:
        """Initialize (or reset) the singleton for a new compile run."""
        cls._instance = cls(mellea_package_dir)

    @classmethod
    def record_args(cls, **compile_args) -> None:
        inst = cls._require_init()
        inst._metadata["compile_args"] = compile_args
        inst._dump()

    @classmethod
    def record_backend(
        cls, backend: Literal["claude", "bob"], backend_model: Optional[str] = None
    ) -> None:
        inst = cls._require_init()
        inst._metadata["compiler"] = {
            "backend": backend,
            "version": _get_backend_version(backend),
            "model": backend_model,
        }
        inst._dump()

    @classmethod
    def record_melleafy(cls, mellea_dir) -> None:
        cls._mellea_package_dir = mellea_dir
        inst = cls._require_init()
        melleafy_path = inst._mellea_package_dir / "melleafy.json"
        melleafy_data = None
        if melleafy_path.exists():
            try:
                melleafy_data = json.loads(melleafy_path.read_text())
            except json.JSONDecodeError:
                pass
        inst._metadata["melleafy"] = melleafy_data
        inst._dump()

    @classmethod
    def record_completion(cls) -> None:
        inst = cls._require_init()
        inst._metadata["compiled_at"] = inst._get_current_timestamp()
        inst._dump()

    def _dump(self) -> None:
        """Write current metadata to compile_metadata.json."""
        output_path = self._mellea_package_dir / "compile_metadata.json"
        try:
            with open(output_path, "w") as f:
                json.dump(self._metadata, f, indent=4, default=str)
        except (OSError, TypeError, ValueError) as e:
            LOGGER.warning("Failed to write compile metadata to %s: %s", output_path, e)


def _git_info() -> Dict[str, Optional[str]]:
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return {"branch": branch, "commit_hash": commit_hash}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"branch": None, "commit_hash": None}


def _get_backend_version(backend: str) -> Optional[str]:
    try:
        backend_version = subprocess.check_output(
            [backend, "--version"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return backend_version
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _get_mellea_version():
    try:
        return importlib.metadata.version("mellea")
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError("mellea package not installed.")
