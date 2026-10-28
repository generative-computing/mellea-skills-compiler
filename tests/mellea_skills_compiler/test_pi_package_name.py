"""Keep the pi extension's npm package name the same everywhere.

The extension is published as ``@ibm/mellea-skills-compiler-pi``. If
``package.json``, its lockfile and the install docs disagree, ``npm ci``
fails or users are told to install a package that doesn't exist.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

PACKAGE_NAME = "@ibm/mellea-skills-compiler-pi"
INSTALL_COMMAND = f"pi install npm:{PACKAGE_NAME}"
INSTALL_DOCS = ["docs/PI_SETUP.md", "extensions/pi/README.md"]

# The unscoped name on its own, not as the tail of the scoped one.
_UNSCOPED_NAME = re.compile(r"(?<!@ibm/)\bmellea-skills-compiler-pi\b")


def test_package_json_uses_scoped_name():
    package = json.loads((REPO_ROOT / "extensions/pi/package.json").read_text())
    assert package["name"] == PACKAGE_NAME
    # A new scoped package is private by default, which npm refuses on a
    # free account; this saves passing --access public on every publish.
    assert package["publishConfig"] == {"access": "public"}


def test_lockfile_matches_package_name():
    lock = json.loads((REPO_ROOT / "extensions/pi/package-lock.json").read_text())
    assert lock["name"] == PACKAGE_NAME
    assert lock["packages"][""]["name"] == PACKAGE_NAME


@pytest.mark.parametrize("doc", INSTALL_DOCS)
def test_install_docs_use_scoped_name(doc):
    found = INSTALL_COMMAND in (REPO_ROOT / doc).read_text()
    assert found, f"{doc} does not contain `{INSTALL_COMMAND}`"


def test_no_tracked_docs_use_unscoped_name():
    # Tracked files only: a local checkout can hold untracked Markdown.
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    offenders = [
        f"{path}:{lineno}"
        for path in tracked
        for lineno, line in enumerate((REPO_ROOT / path).read_text().splitlines(), 1)
        if _UNSCOPED_NAME.search(line)
    ]
    assert offenders == []
