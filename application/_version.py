"""Single source of truth for the cmdbsyncer version.

Regenerated from the newest ``changelog/v*.md`` entry by ``make sync-version``.
Kept as a standalone module so ``pyproject.toml`` can resolve the version via
``[tool.setuptools.dynamic]`` without importing the Flask application.
"""
import os
import re

__version__ = "3.12.12"


def _has_unreleased_entries():
    """True when the active changelog still carries an ``## Unreleased``
    section with entries above the first ``## Version x.y.z`` block."""
    parts = __version__.split('.')
    fname = f"v{parts[0]}.{parts[1]}.md"
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
            r'^##\s+Unreleased\s*$(.*?)(?=^##\s|\Z)',
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
    return f"{__version__}-dev" if _has_unreleased_entries() else __version__
