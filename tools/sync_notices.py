#!/usr/bin/env python3
"""Copy user-facing notice files into the package for wheel distribution.

In source checkouts the admin index view reads notice ``*.txt`` files from
``notices/`` at the repository root. PyPI installs only ship the
``application/`` package, so the files need to live alongside the package
code as well. This script is wired into ``make sync`` (and therefore
``make build``) to keep ``application/notices/`` in lockstep with the
repo-root ``notices/`` directory.
"""
import glob
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTICES_SRC = os.path.join(ROOT, "notices")
NOTICES_DST = os.path.join(ROOT, "application", "notices")


def main():
    """Mirror ``notices/*.txt`` into ``application/notices/``."""
    if not os.path.isdir(NOTICES_SRC):
        sys.exit(f"no notices directory at {NOTICES_SRC}")

    if os.path.isdir(NOTICES_DST):
        shutil.rmtree(NOTICES_DST)
    os.makedirs(NOTICES_DST)

    sources = sorted(glob.glob(os.path.join(NOTICES_SRC, "*.txt")))
    for source in sources:
        shutil.copyfile(source, os.path.join(NOTICES_DST, os.path.basename(source)))

    print(
        f"Synced {len(sources)} notice file(s) → "
        f"{os.path.relpath(NOTICES_DST, ROOT)}/"
    )


if __name__ == "__main__":
    main()
