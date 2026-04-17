#!/usr/bin/env python3
"""Sync the cmdbsyncer version into ``_version.py`` and ``pyproject.toml``.

Reads the newest ``## Version x.y.z`` header from ``changelog/v*.md`` and
writes it to both files so the Flask app at runtime, the installed wheel,
and the PyPI metadata stay in lockstep.
"""
import glob
import os
import re
import sys

import tomlkit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG_GLOB = os.path.join(ROOT, "changelog", "v*.md")
VERSION_FILE = os.path.join(ROOT, "application", "_version.py")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")

TEMPLATE = '''\
"""Single source of truth for the cmdbsyncer version.

Regenerated from the newest ``changelog/v*.md`` entry by ``make sync-version``.
Kept as a standalone module so ``pyproject.toml`` can resolve the version via
``[tool.setuptools.dynamic]`` without importing the Flask application.
"""

__version__ = "{version}"
'''


def _file_key(path):
    """Sort key that orders ``v{major}.{minor}.md`` paths numerically."""
    match = re.search(r"v(\d+)\.(\d+)\.md$", path)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def find_latest_version():
    """Return the newest ``## Version x.y.z`` header across all changelog files."""
    for path in sorted(glob.glob(CHANGELOG_GLOB), key=_file_key, reverse=True):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                match = re.match(r"^## Version (\d+\.\d+\.\d+)\s*$", line)
                if match:
                    return match.group(1)
    return None


def write_version_file(version):
    """Write ``application/_version.py``, returns True if the file changed."""
    new = TEMPLATE.format(version=version)
    old = None
    if os.path.isfile(VERSION_FILE):
        with open(VERSION_FILE, encoding="utf-8") as fh:
            old = fh.read()
    if old == new:
        return False
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def write_pyproject_version(version):
    """Update ``[project] version`` in pyproject.toml; returns True if changed."""
    with open(PYPROJECT, encoding="utf-8") as fh:
        doc = tomlkit.parse(fh.read())
    current = str(doc["project"]["version"])
    if current == version:
        return False
    doc["project"]["version"] = version
    with open(PYPROJECT, "w", encoding="utf-8") as fh:
        fh.write(tomlkit.dumps(doc))
    return True


def main():
    """Resolve the latest version and sync it into both files."""
    version = find_latest_version()
    if not version:
        sys.exit("no '## Version x.y.z' header found in changelog/v*.md")
    changes = []
    if write_version_file(version):
        changes.append(os.path.relpath(VERSION_FILE, ROOT))
    if write_pyproject_version(version):
        changes.append(os.path.relpath(PYPROJECT, ROOT))
    if changes:
        print(f"Synced version {version} → " + ", ".join(changes))
    else:
        print(f"Version {version} already in sync")


if __name__ == "__main__":
    main()
