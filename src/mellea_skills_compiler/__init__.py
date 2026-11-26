"""Mellea Skills Compiler — Agent specification certification pipeline.

Transforms agent skill specifications into policy-governed, certified pipelines
with evidence packages documenting risks, compliance posture, and runtime governance.
"""

__version__ = "0.3.1"

import os as _os

# The ollama client reads only OLLAMA_HOST; treat OLLAMA_API_URL as an alias.
if not _os.environ.get("OLLAMA_HOST") and _os.environ.get("OLLAMA_API_URL"):
    _os.environ["OLLAMA_HOST"] = _os.environ["OLLAMA_API_URL"]
