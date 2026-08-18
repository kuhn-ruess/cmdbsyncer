"""
Invariants for the `local_config.py` editor presets.

A config key only becomes discoverable when it appears in a preset
*and* carries a BaseConfig default — a key that has neither is
effectively invisible in the UI, which is how OIDC login ended up
being configurable only by hand-editing local_config.py.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import unittest


def _load(dotted, *relpath):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, *relpath)
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


_PRESETS = _load('application.helpers.local_config_presets',
                 'application', 'helpers', 'local_config_presets.py')
_CONFIG = _load('application.config', 'application', 'config.py')

PRESETS = _PRESETS.PRESETS
BaseConfig = _CONFIG.BaseConfig

VALID_TYPES = {'str', 'int', 'float', 'bool', 'none'}


class TestLocalConfigPresets(unittest.TestCase):

    def test_every_key_has_a_baseconfig_default(self):
        # Without a default the editor cannot restore the key after a
        # delete, and admins have no way to see what the value would be.
        for preset in PRESETS:
            for entry in preset['keys']:
                self.assertTrue(
                    hasattr(BaseConfig, entry['key']),
                    f"{preset['ident']}: {entry['key']} has no BaseConfig default",
                )

    def test_no_key_belongs_to_two_presets(self):
        # The editor groups existing rows by key -> preset, so a key
        # claimed twice silently shows up under the wrong heading.
        owner = {}
        for preset in PRESETS:
            for entry in preset['keys']:
                key = entry['key']
                self.assertNotIn(
                    key, owner,
                    f"{key} is in both '{owner.get(key)}' and '{preset['ident']}'",
                )
                owner[key] = preset['ident']

    def test_entries_are_well_formed(self):
        idents = set()
        for preset in PRESETS:
            self.assertNotIn(preset['ident'], idents)
            idents.add(preset['ident'])
            self.assertTrue(preset['name'])
            self.assertTrue(preset['description'])
            self.assertTrue(preset['keys'])
            for entry in preset['keys']:
                self.assertIn(entry['type'], VALID_TYPES)
                self.assertEqual(entry['key'], entry['key'].upper())

    def test_default_matches_declared_type(self):
        checkers = {
            'str': str, 'int': int, 'float': float, 'bool': bool,
        }
        for preset in PRESETS:
            for entry in preset['keys']:
                if entry['type'] == 'none':
                    self.assertIsNone(entry['default'])
                    continue
                # bool is a subclass of int — check it first.
                if entry['type'] == 'int':
                    self.assertNotIsInstance(entry['default'], bool)
                self.assertIsInstance(entry['default'], checkers[entry['type']])

    def test_oidc_preset_covers_the_flat_keys(self):
        # The nested OIDC_ROLE_MAPPING stays on disk, everything else
        # must be reachable from the UI.
        preset = _PRESETS.get_preset('oidc')
        self.assertIsNotNone(preset)
        keys = {entry['key'] for entry in preset['keys']}
        self.assertEqual(keys, {
            'OIDC_LOGIN', 'OIDC_ACCOUNT', 'OIDC_SCOPES',
            'OIDC_EMAIL_CLAIM', 'OIDC_NAME_CLAIM', 'OIDC_GROUPS_CLAIM',
            'OIDC_REQUIRED_GROUP', 'OIDC_AUTO_CREATE',
            'OIDC_ADMIN_GROUP', 'OIDC_DEFAULT_ROLES',
        })


if __name__ == '__main__':
    unittest.main()
