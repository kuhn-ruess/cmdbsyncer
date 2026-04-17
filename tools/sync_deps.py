#!/usr/bin/env python3
"""Sync ``[project.dependencies]`` in ``pyproject.toml`` from ``requirements.txt``.

Only the core runtime requirements are reflected on PyPI. The platform-heavy
groups (``requirements-ansible.txt``, ``requirements-extras.txt``) stay
repo-local — they pull in compiled extensions (ODBC, LDAP, Kerberos, vmware)
that would turn a clean ``pip install cmdbsyncer`` into a build-from-source
marathon.

Comments (``#``) and blank lines are ignored. The rest of ``pyproject.toml``
is preserved byte-for-byte via tomlkit.
"""
import os
import sys

import tomlkit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")


def read_requirements(path):
    """Return a list of requirement strings from ``path``, stripped of comments."""
    if not os.path.isfile(path):
        sys.exit(f"requirements file not found: {path}")
    out = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def make_array(items):
    """Build a multi-line tomlkit array so diffs stay one-entry-per-line."""
    array = tomlkit.array()
    array.multiline(True)
    for item in items:
        array.append(item)
    return array


def main():
    """Sync ``[project.dependencies]`` from ``requirements.txt``."""
    with open(PYPROJECT, encoding="utf-8") as fh:
        doc = tomlkit.parse(fh.read())

    items = read_requirements(REQUIREMENTS)
    before = list(doc["project"].get("dependencies", []))
    doc["project"]["dependencies"] = make_array(items)

    with open(PYPROJECT, "w", encoding="utf-8") as fh:
        fh.write(tomlkit.dumps(doc))

    if before == items:
        print("pyproject.toml dependencies already in sync")
    else:
        print(f"Updated pyproject.toml dependencies: {len(before)} -> {len(items)} packages")


if __name__ == "__main__":
    main()
