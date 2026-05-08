#!/usr/bin/env python3
"""Bump the trailing pre-release counter in ``pyproject.toml``.

Used by ``make release-pre`` to ship sequential test builds (`.devN`,
`rcN`, …) without requiring the operator to hand-edit the version
string before each upload. PEP 440 sorts the recognised pre-release
forms below any final release, so a ``--pre`` install picks them up
while normal ``pip install <pkg>`` ignores them.

Recognised forms — only the trailing integer is incremented:
    4.1.0.dev0  -> 4.1.0.dev1
    4.1.0a1     -> 4.1.0a2
    4.1.0b3     -> 4.1.0b4
    4.1.0rc7    -> 4.1.0rc8

Plain final versions (``4.1.0``) are refused — the operator has to
explicitly start a new pre-release line so the next dev cycle's base
version is a conscious decision, not a side effect of running this
script.
"""
import re
import sys
from pathlib import Path


_VERSION_LINE_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")\s*$')
_PRE_RELEASE_RE = re.compile(
    r'^(?P<base>\d+\.\d+\.\d+)(?P<sep>\.dev|a|b|rc)(?P<n>\d+)$'
)


def bump(version: str) -> str:
    """Return the next pre-release counter for *version* or raise SystemExit."""
    match = _PRE_RELEASE_RE.match(version)
    if not match:
        raise SystemExit(
            f"Refusing to bump {version!r}: not a recognised pre-release "
            f"form (expected X.Y.Z.devN / aN / bN / rcN). Hand-edit "
            f"pyproject.toml to start a new pre-release line."
        )
    return f"{match['base']}{match['sep']}{int(match['n']) + 1}"


def main():
    """Bump the version line in the pyproject.toml passed as argv[1]."""
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'pyproject.toml')
    if not path.is_file():
        raise SystemExit(f"Not found: {path}")

    new_lines = []
    bumped_from = bumped_to = None
    for line in path.read_text(encoding='utf-8').splitlines(keepends=True):
        match = _VERSION_LINE_RE.match(line.rstrip('\n').rstrip('\r'))
        if match and bumped_from is None:
            bumped_from = match.group(2)
            bumped_to = bump(bumped_from)
            new_lines.append(f'{match.group(1)}{bumped_to}{match.group(3)}\n')
        else:
            new_lines.append(line)

    if bumped_from is None:
        raise SystemExit(f'No version = "..." line found in {path}')

    path.write_text(''.join(new_lines), encoding='utf-8')
    print(f"{path}: {bumped_from} -> {bumped_to}")


if __name__ == '__main__':
    main()
