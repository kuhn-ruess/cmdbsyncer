#!/usr/bin/env python3
"""Sync the cmdbsyncer version into ``_version.py`` and ``pyproject.toml``.

On ``main`` the newest ``## Version x.y.z`` header from ``changelog/v*.md``
wins. On the LTS branch (``.lts-release`` marker present, contents = the
``MAJOR.MINOR`` base line, e.g. ``3.12``) the newest
``## Version {base}-LTS{n}`` header wins and is written as display ``3.12-LTS{n}``
/ PEP 440 ``3.12+lts{n}``. LTS branches must not carry an ``## Unreleased``
section — sync aborts when one is found — so LTS builds never show ``-dev``.
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

UNRELEASED_RE = re.compile(
    r"^##\s+Unreleased\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)

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
    section with entries above the first ``## Version …`` block."""
    base = __version__.split('-', 1)[0]
    parts = base.split('.')
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
    entries are pending. LTS builds carry an ``-LTSn`` counter in
    ``__version__`` and never show ``-dev`` because the LTS changelog is not
    allowed to contain an ``## Unreleased`` section."""
    if '-LTS' in __version__:
        return __version__
    return f"{{__version__}}-dev" if _has_unreleased_entries() else __version__
'''


def _file_key(path):
    """Sort key that orders ``v{major}.{minor}.md`` paths numerically."""
    match = re.search(r"v(\d+)\.(\d+)\.md$", path)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _read_lts_base():
    """Return ``MAJOR.MINOR`` from ``.lts-release`` (stripped)."""
    with open(LTS_MARKER, encoding="utf-8") as fh:
        base = fh.read().strip()
    if not re.fullmatch(r"\d+\.\d+", base):
        sys.exit(
            f".lts-release must contain a MAJOR.MINOR base version like '3.12', "
            f"got {base!r}"
        )
    return base


def _lts_changelog_path(base):
    """Return the path to the ``v{base}.md`` changelog file for an LTS line."""
    major, minor = base.split(".")
    return os.path.join(ROOT, "changelog", f"v{major}.{minor}.md")


def _abort_if_unreleased(path):
    """Abort when the given changelog still carries an ``## Unreleased``
    section with entries — not allowed on LTS."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    match = UNRELEASED_RE.search(text)
    if match and match.group(1).strip():
        sys.exit(
            f"{os.path.relpath(path, ROOT)} still contains an '## Unreleased' "
            f"section. LTS branches must not use '## Unreleased' — rename it "
            f"to the next '## Version {{base}}-LTS{{n}}' header before syncing."
        )


def find_latest_lts_version(base):
    """Return the newest ``## Version {base}-LTS{n}`` counter for the LTS base."""
    path = _lts_changelog_path(base)
    if not os.path.isfile(path):
        return None
    pattern = re.compile(
        rf"^## Version {re.escape(base)}-LTS(\d+)\s*$"
    )
    best = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            match = pattern.match(line)
            if match:
                n = int(match.group(1))
                if best is None or n > best:
                    best = n
    return best


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
    if os.path.isfile(LTS_MARKER):
        base = _read_lts_base()
        _abort_if_unreleased(_lts_changelog_path(base))
        counter = find_latest_lts_version(base)
        if counter is None:
            sys.exit(
                f"no '## Version {base}-LTS<n>' header found in "
                f"{os.path.relpath(_lts_changelog_path(base), ROOT)} — "
                f"add one before syncing"
            )
        display_version = f"{base}-LTS{counter}"
        pep440_version = f"{base}+lts{counter}"
    else:
        version = find_latest_version()
        if not version:
            sys.exit("no '## Version x.y.z' header found in changelog/v*.md")
        display_version = version
        pep440_version = version
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
