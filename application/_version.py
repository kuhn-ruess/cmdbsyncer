"""Single source of truth for the cmdbsyncer version.

Reads the current version at import time from the newest
``application/changelog/v*.md`` file. The display variant adds a ``-dev``
suffix while an ``## Unreleased`` section is open. LTS branches carry a
``.lts-release`` marker at the repo root holding the ``MAJOR.MINOR`` base
line; the version is then derived from the highest
``## Version {base}-LTS{n}`` header in ``v{base}.md``.
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_CHANGELOG_DIR = os.path.join(_HERE, 'changelog')
_LTS_MARKER = os.path.join(os.path.dirname(_HERE), '.lts-release')

_VERSION_HEADER_RE = re.compile(r'^## Version (\d+\.\d+\.\d+)\s*$')
_FILE_NAME_RE = re.compile(r'^v(\d+)\.(\d+)\.md$')
_UNRELEASED_RE = re.compile(
    r'^##\s+Unreleased\s*$(.*?)(?=^##\s|\Z)', re.MULTILINE | re.DOTALL,
)


def _read_lts_base():
    """Return ``MAJOR.MINOR`` from ``.lts-release`` or None."""
    try:
        with open(_LTS_MARKER, encoding='utf-8') as fh:
            base = fh.read().strip()
    except OSError:
        return None
    return base if re.fullmatch(r'\d+\.\d+', base) else None


def _resolve_lts_version(base):
    """Return ``{base}+lts{n}`` for the highest LTS counter, or None."""
    path = os.path.join(_CHANGELOG_DIR, f'v{base}.md')
    if not os.path.isfile(path):
        return None
    pattern = re.compile(rf'^## Version {re.escape(base)}-LTS(\d+)\s*$')
    best = None
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            match = pattern.match(line)
            if match:
                n = int(match.group(1))
                if best is None or n > best:
                    best = n
    return f'{base}+lts{best}' if best is not None else None


def _resolve_main_version():
    """Return the newest ``## Version x.y.z`` across all ``v*.md`` files."""
    if not os.path.isdir(_CHANGELOG_DIR):
        return None
    candidates = []
    for name in os.listdir(_CHANGELOG_DIR):
        match = _FILE_NAME_RE.match(name)
        if match:
            candidates.append((int(match.group(1)), int(match.group(2)), name))
    candidates.sort(reverse=True)
    for _, _, name in candidates:
        with open(os.path.join(_CHANGELOG_DIR, name), encoding='utf-8') as fh:
            for line in fh:
                match = _VERSION_HEADER_RE.match(line)
                if match:
                    return match.group(1)
    return None


def _resolve_version():
    """Return the PEP 440 version, or '0.0.0' as a last-resort fallback."""
    base = _read_lts_base()
    if base:
        version = _resolve_lts_version(base)
        if version:
            return version
    return _resolve_main_version() or '0.0.0'


__version__ = _resolve_version()


def _has_unreleased_entries():
    """True when the active changelog still carries an ``## Unreleased``
    section with content."""
    base = __version__.split('+', 1)[0].split('-', 1)[0]
    parts = base.split('.')
    path = os.path.join(_CHANGELOG_DIR, f'v{parts[0]}.{parts[1]}.md')
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    match = _UNRELEASED_RE.search(text)
    return bool(match and match.group(1).strip())


def _installed_version():
    """The version recorded in installed-package metadata, or None.

    `pyproject.toml` carries the authoritative pre-release counter
    (``4.1.0.dev22`` etc.) but is gone after ``pip install``. The wheel's
    dist-info keeps it, so ``importlib.metadata`` recovers the suffix on
    both PyPI installs and editable installs. Source checkouts without
    an installation just fall through to the changelog-derived version.
    """
    try:
        from importlib.metadata import (  # pylint: disable=import-outside-toplevel
            PackageNotFoundError, version as _md_version,
        )
        return _md_version('cmdbsyncer')
    except (PackageNotFoundError, ImportError, ModuleNotFoundError):
        return None


def get_display_version():
    """Display form: ``4.0.0`` / ``4.0.0-dev22`` / ``3.12-LTS3``.

    Resolution:
    - LTS lines keep their ``-LTS`` suffix (PEP 440 stores it as ``+lts``).
    - If the installed metadata carries a pre-release suffix (``.devN``,
      ``aN``, ``bN``, ``rcN``), surface it as ``-dev22`` / ``-rc1`` etc.
      so users can tell which dev build they are on.
    - Otherwise, while an ``## Unreleased`` section is still open in the
      active changelog, append a bare ``-dev`` (source checkouts before
      the next pre-release is cut).
    """
    if '+lts' in __version__:
        return __version__.replace('+lts', '-LTS')
    installed = _installed_version()
    if installed:
        match = re.search(r'\.(dev\d+|a\d+|b\d+|rc\d+)$', installed)
        if match:
            base = installed[:match.start()]
            return f'{base}-{match.group(1)}'
    return f'{__version__}-dev' if _has_unreleased_entries() else __version__
