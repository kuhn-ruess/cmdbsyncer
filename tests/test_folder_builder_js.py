"""
Regression tests for the Checkmk folder-attribute editor's value parser.

The editor takes the ``folder|{'title': 'X'}`` syntax apart in the browser.
Jinja blocks are masked with a control-character placeholder first, so a
``{{ os|lower }}`` cannot be mistaken for the ``|`` that separates a folder
from its options. A block inside a *quoted* value — the normal way to write
Jinja in an attribute — came back still masked, so the field showed the raw
placeholder and saving wrote those control characters into the rule.

The parser is plain JavaScript in the template and is exercised here
through node, which the test skips when it is not installed.
"""
# pylint: disable=missing-function-docstring
import json
import os
import shutil
import subprocess
import unittest

_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'application', 'templates', 'admin', 'model', '_folder_builder.html')

# The pure part of the editor: masking, the Python-literal parser and the
# serializer, up to the first function that touches the DOM.
_SECTION_START = '// -- Jinja masking'
_SECTION_END = '// -- Small DOM helpers'


def _parser_source():
    with open(_TEMPLATE, encoding='utf-8') as template:
        text = template.read()
    return text[text.index(_SECTION_START):text.index(_SECTION_END)]


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class FolderBuilderParserTest(unittest.TestCase):
    """parseParam() / dumpParam() in admin/model/_folder_builder.html"""

    def _round_trip(self, value):
        """Parse `value` the way the editor does and write it back out."""
        script = _parser_source() + (
            f"process.stdout.write(dumpParam(parseParam({json.dumps(value)})));")
        result = subprocess.run(['node', '-e', script], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_jinja_inside_a_quoted_value_survives(self):
        value = "servers|{'title': '{{ os }} Server'}"
        self.assertEqual(self._round_trip(value), value)

    def test_no_control_characters_are_written_back(self):
        # The masking placeholder must never reach the saved value — the
        # browser cannot display it, and Checkmk would receive it verbatim.
        out = self._round_trip("servers|{'title': 'team_{{ x }}'}")
        self.assertNotIn('\x01', out)

    def test_jinja_in_the_folder_name_survives(self):
        value = "{{ os|lower }}/servers|{'title': 'Servers'}"
        self.assertEqual(self._round_trip(value), value)

    def test_bare_expression_stays_bare(self):
        # A whole list produced by an expression is the one place a value is
        # not quoted — that path already worked and must keep working.
        value = "servers|{'parents': {{ parents.split(',') }}}"
        self.assertEqual(self._round_trip(value), value)

    def test_quotes_inside_a_jinja_block_stay_unescaped(self):
        # 'default()' carries its own quotes. Escaping them would reach the
        # renderer as default(\'x\') and break the expression — the export
        # renders the value before it reads the dict.
        value = "servers|{'title': '{{ os|default('x') }} Server'}"
        self.assertEqual(self._round_trip(value), value)

    def test_quotes_outside_a_jinja_block_are_still_escaped(self):
        # The literal part still has to survive as a Python string.
        out = self._round_trip("servers|{'title': \"it's {{ os }}\"}")
        self.assertEqual(out, "servers|{'title': 'it\\'s {{ os }}'}")

    def test_plain_value_is_untouched(self):
        value = "servers|{'title': 'Web Servers', 'site': 'main'}"
        self.assertEqual(self._round_trip(value), value)


if __name__ == '__main__':
    unittest.main()
