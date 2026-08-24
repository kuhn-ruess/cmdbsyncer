"""The `.rule-disabled` marker has to be styled without a theme, too.

The marker class is set by the tail script in `admin/master.html` on
every list row whose `enabled` flag is off. Styling it only inside the
theme files left the default theme — which loads no theme CSS at all —
without any marker, so a disabled rule looked exactly like an active
one. The base stylesheet carries the fallback; the themes override it.
"""
# pylint: disable=missing-function-docstring

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_CSS = os.path.join(REPO_ROOT, 'application', 'static', 'css', 'cmdbsyncer.css')
THEME_DIR = os.path.join(REPO_ROOT, 'application', 'themes')

# A declaration block that mentions .rule-disabled and paints something.
_BLOCK = re.compile(r'([^{}]*\.rule-disabled[^{}]*)\{([^}]*)\}', re.MULTILINE)


def _painted_properties(path):
    """Property names declared for .rule-disabled in *path*."""
    with open(path, encoding='utf-8') as handle:
        css = handle.read()
    props = set()
    for _selector, body in _BLOCK.findall(css):
        for declaration in body.split(';'):
            if ':' in declaration:
                props.add(declaration.split(':', 1)[0].strip())
    return props


class DisabledRowStyleTests(unittest.TestCase):
    """Every stylesheet has to paint a switched-off row."""

    def test_base_stylesheet_marks_disabled_rows(self):
        props = _painted_properties(BASE_CSS)
        self.assertIn('background-color', props)
        self.assertIn('color', props)

    def test_every_theme_keeps_its_own_marker(self):
        themes = [name for name in os.listdir(THEME_DIR) if name.endswith('.css')]
        self.assertTrue(themes, 'no themes found')
        for name in themes:
            with self.subTest(theme=name):
                self.assertIn('background-color',
                              _painted_properties(os.path.join(THEME_DIR, name)))
