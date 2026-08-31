"""
Custom fields every account gets, whatever its plugin type
"""
# pylint: disable=missing-function-docstring
import importlib.util
import os
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_plugins_helper():
    """The real helper module — it only needs os and json."""
    spec = importlib.util.spec_from_file_location(
        "tests._plugins_helper_real",
        os.path.join(REPO_ROOT, "application", "helpers", "plugins.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGlobalAccountPresets(unittest.TestCase):
    """Tests for the global custom field presets in discover_plugins"""

    def setUp(self):
        self.helper = _load_plugins_helper()
        self.plugin = {'ident': 'demo', 'name': 'Demo',
                       'account_custom_field_presets': {'tables': 'cmdb_ci_server'}}

    def _discover(self):
        with patch.object(self.helper, '_disabled_idents', return_value=set()), \
             patch.object(self.helper, '_plugin_data_cache',
                          return_value={'demo': self.plugin}):
            return self.helper.discover_plugins()

    def test_every_plugin_offers_the_global_fields(self):
        presets = self._discover()['demo']['account_custom_field_presets']
        self.assertIn('custom_headers', presets)
        self.assertEqual(presets['tables'], 'cmdb_ci_server')

    def test_a_plugin_without_presets_still_gets_them(self):
        self.plugin = {'ident': 'demo', 'name': 'Demo'}
        self.assertIn('custom_headers',
                      self._discover()['demo']['account_custom_field_presets'])

    def test_the_plugins_own_value_wins(self):
        self.plugin['account_custom_field_presets']['custom_headers'] = 'X-Own: 1'
        presets = self._discover()['demo']['account_custom_field_presets']
        self.assertEqual(presets['custom_headers'], 'X-Own: 1')

    def test_the_cached_plugin_data_is_not_changed(self):
        # discover_plugins() is called per request; mutating the cache
        # would grow it with every call
        self._discover()
        self.assertNotIn('custom_headers', self.plugin['account_custom_field_presets'])

    def test_a_type_registered_from_code_gets_them_too(self):
        # Enterprise registers its account types this way
        self.helper.register_plugin_type('ent', "Enterprise")
        presets = self._discover()['ent']['account_custom_field_presets']
        self.assertIn('custom_headers', presets)
