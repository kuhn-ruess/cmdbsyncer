#!/usr/bin/env python3
"""Set ``pyproject.toml`` to the next ``.devN`` pre-release of its version.

Used by ``make release-pre`` to ship sequential test builds from ``main``.
``pyproject.toml`` carries the upcoming final version (``4.5.0``); this
script asks PyPI which ``4.5.0.devN`` builds already exist and writes the
next one (``4.5.0.dev0`` for the first). The Makefile restores the
original file after the build, so nothing has to be committed.

PEP 440 sorts ``.devN`` below the final release, so ``pip install --pre``
picks them up while a normal ``pip install`` ignores them.

A base version that is already released on PyPI is refused — bump
``pyproject.toml`` to the next version first.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


_VERSION_LINE_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")\s*$')
_NAME_LINE_RE = re.compile(r'^name\s*=\s*"([^"]+)"\s*$')
_FINAL_RE = re.compile(r'^\d+\.\d+\.\d+$')


def released_versions(package):
    """Return all version strings PyPI knows for *package*."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return set(json.load(response)['releases'])
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return set()
        raise


def next_dev(base, existing):
    """Return the next ``base.devN`` not yet in *existing*."""
    if not _FINAL_RE.match(base):
        raise SystemExit(
            f"Refusing {base!r}: pyproject.toml must hold a plain X.Y.Z "
            f"version, the .devN suffix is added here."
        )
    if base in existing:
        raise SystemExit(
            f"{base} is already released on PyPI — bump pyproject.toml "
            f"to the next version first."
        )
    dev_re = re.compile(rf'^{re.escape(base)}\.dev(\d+)$')
    numbers = [int(m[1]) for m in map(dev_re.match, existing) if m]
    return f"{base}.dev{max(numbers) + 1 if numbers else 0}"


def main():
    """Rewrite the version line in the pyproject.toml passed as argv[1]."""
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'pyproject.toml')
    if not path.is_file():
        raise SystemExit(f"Not found: {path}")

    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    package = next((m[1] for m in map(_NAME_LINE_RE.match, lines) if m), None)
    index = next((i for i, line in enumerate(lines)
                  if _VERSION_LINE_RE.match(line.rstrip('\r\n'))), None)
    if package is None or index is None:
        raise SystemExit(f'No name/version line found in {path}')

    match = _VERSION_LINE_RE.match(lines[index].rstrip('\r\n'))
    new_version = next_dev(match[2], released_versions(package))
    lines[index] = f'{match[1]}{new_version}{match[3]}\n'
    path.write_text(''.join(lines), encoding='utf-8')
    print(f"{path}: {match[2]} -> {new_version}")


if __name__ == '__main__':
    main()
