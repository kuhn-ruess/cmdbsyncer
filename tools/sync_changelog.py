#!/usr/bin/env python3
"""Copy the active release changelog into the package for wheel distribution.

In source checkouts the in-app changelog view reads from the symlink
``changelog.md`` at the repository root. PyPI installs only ship the
``application/`` package, so the file needs to live alongside the package
code as well. This script is wired into ``make sync`` (and therefore
``make build``) to keep ``application/changelog.md`` in lockstep with the
newest ``changelog/v*.md`` entry.
"""
import glob
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG_GLOB = os.path.join(ROOT, "changelog", "v*.md")
PACKAGED_CHANGELOG = os.path.join(ROOT, "application", "changelog.md")


def _file_key(path):
    """Sort key that orders ``v{major}.{minor}.md`` paths numerically."""
    match = re.search(r"v(\d+)\.(\d+)\.md$", path)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def main():
    """Resolve the newest version's changelog file and copy it in-place."""
    candidates = sorted(glob.glob(CHANGELOG_GLOB), key=_file_key, reverse=True)
    if not candidates:
        sys.exit("no changelog/v*.md files found")
    source = candidates[0]
    shutil.copyfile(source, PACKAGED_CHANGELOG)
    print(
        f"Synced changelog {os.path.relpath(source, ROOT)} → "
        f"{os.path.relpath(PACKAGED_CHANGELOG, ROOT)}"
    )


if __name__ == "__main__":
    main()
