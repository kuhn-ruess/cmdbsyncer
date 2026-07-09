"""Tests for `get_ruletype_by_filename` — gh issue #122."""
# pylint: disable=missing-function-docstring,missing-class-docstring,wrong-import-position

import importlib.util
import os
import sys
import types
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Swap the stubbed enabled_rules from tests/__init__.py for a real
# minimal mapping, then re-load `rule_import_export` directly from
# disk so it sees a working `enabled_rules` dict. We deliberately
# bypass the package-stub graph because the function under test only
# needs the mapping — pulling in the real Flask/Mongo modules would
# be overkill for a pure-string lookup.
_defs = types.ModuleType('application.plugins.rules.rule_definitions')
_defs.rules = {
    'custom_attributes':
        ('application.modules.custom_attributes.models', 'CustomAttributeRule'),
    'cmk_filter':
        ('application.plugins.checkmk.models', 'CheckmkFilterRule'),
}
sys.modules['application.plugins.rules.rule_definitions'] = _defs

_MOD_PATH = os.path.join(
    REPO_ROOT, 'application', 'plugins', 'rules', 'rule_import_export.py',
)
_MODULE_NAME = 'application.plugins.rules.rule_import_export'
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = mod
_spec.loader.exec_module(mod)
get_ruletype_by_filename = mod.get_ruletype_by_filename


class GetRuletypeByFilenameTests(unittest.TestCase):
    def test_filename_with_timestamp_resolves_rule_type(self):
        self.assertEqual(
            get_ruletype_by_filename('CustomAttributeRule_202604120815.syncer_json'),
            'custom_attributes',
        )

    def test_filename_without_timestamp_also_resolves(self):
        # The bug from issue #122: when the user renames the export
        # file from `<Model>_<TS>.syncer_json` to `<Model>.syncer_json`
        # the lookup used to fail because `.split('_')[0]` left the
        # extension attached. The fix strips the extension first.
        self.assertEqual(
            get_ruletype_by_filename('CustomAttributeRule.syncer_json'),
            'custom_attributes',
        )

    def test_filename_with_path_prefix_is_tolerated(self):
        self.assertEqual(
            get_ruletype_by_filename('/uploads/CustomAttributeRule.syncer_json'),
            'custom_attributes',
        )

    def test_unknown_model_returns_false(self):
        self.assertFalse(
            get_ruletype_by_filename('Whatever.syncer_json')
        )

    def test_non_syncer_json_filename_still_attempts_match(self):
        # We don't anchor on the extension — a directory listing or
        # custom CLI invocation may drop the suffix entirely.
        self.assertEqual(
            get_ruletype_by_filename('CheckmkFilterRule'),
            'cmk_filter',
        )


if __name__ == '__main__':
    unittest.main()
