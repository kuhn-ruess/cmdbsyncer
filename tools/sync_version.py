#!/usr/bin/env python3
"""Sync the cmdbsyncer version into ``_version.py`` and ``pyproject.toml``.

Reads the newest ``## Version x.y.z`` header from ``changelog/v*.md`` and
writes it to both files so the Flask app at runtime, the installed wheel,
and the PyPI metadata stay in lockstep.
"""
# pylint: disable=duplicate-code
import glob
import os
import re
import sys

import tomlkit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG_GLOB = os.path.join(ROOT, "changelog", "v*.md")
VERSION_FILE = os.path.join(ROOT, "application", "_version.py")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
LTS_MARKER = os.path.join(ROOT, ".lts-release")

TEMPLATE = '''\
"""Single source of truth for the cmdbsyncer version.

Regenerated from the newest ``changelog/v*.md`` entry by ``make sync-version``.
Kept as a standalone module so ``pyproject.toml`` can resolve the version via
``[tool.setuptools.dynamic]`` without importing the Flask application.
"""
import os
import re

__version__ = "{version}"


def _has_unreleased_entries():
    """True when the active changelog still carries an ``## Unreleased``
    section with entries above the first ``## Version x.y.z`` block."""
    parts = __version__.split('.')
    fname = f"v{{parts[0]}}.{{parts[1]}}.md"
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    for path in (
        os.path.join(repo_root, 'changelog', fname),
        os.path.join(here, 'changelog.md'),
    ):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            continue
        match = re.search(
            r'^##\\s+Unreleased\\s*$(.*?)(?=^##\\s|\\Z)',
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not match:
            return False
        return bool(match.group(1).strip())
    return False


def get_display_version():
    """Return the version, suffixed with ``-dev`` while unreleased changelog
    entries are pending."""
    return f"{{__version__}}-dev" if _has_unreleased_entries() else __version__
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
    display_version = version
    pep440_version = version
    if os.path.isfile(LTS_MARKER):
        display_version = f"{version}-LTS"
        pep440_version = f"{version}+lts"
    changes = []
    if write_version_file(display_version):
        changes.append(os.path.relpath(VERSION_FILE, ROOT))
    if write_pyproject_version(pep440_version):
        changes.append(os.path.relpath(PYPROJECT, ROOT))
    if display_version == pep440_version:
        label = display_version
    else:
        label = f"{display_version} / {pep440_version}"
    if changes:
        print(f"Synced version {label} → " + ", ".join(changes))
    else:
        print(f"Version {label} already in sync")


if __name__ == "__main__":
    main()
