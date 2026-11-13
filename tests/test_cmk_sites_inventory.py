"""
The Checkmk sites inventory per settings: a server may run one site per
Checkmk Settings entry (for example a production and a test site), and
the inventory of a settings entry carries only its own sites.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import MagicMock, patch

from tests import _load_real_module  # pylint: disable=no-name-in-module

site_syncer = _load_real_module(
    'application.plugins.ansible.site_syncer_under_test',
    'plugins/ansible/site_syncer.py',
)


class SitesOfSettingsTest(unittest.TestCase):

    def _syncer(self, settings=None):
        syncer = site_syncer.SyncSites.__new__(site_syncer.SyncSites)
        syncer.settings = settings
        syncer.get_site_data = lambda site: {'cmk_site': site.name}
        return syncer

    @staticmethod
    def _site(name, server):
        site = MagicMock()
        site.name = name
        site.server_address = server
        return site

    def test_settings_limit_the_query(self):
        settings = MagicMock()
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = [self._site('test', 'srv01')]
            inventory = self._syncer(settings).get_full_inventory()
        model.objects.assert_called_once_with(enabled=True, settings_master=settings)
        self.assertEqual(inventory['all']['hosts'], ['srv01'])
        self.assertEqual(inventory['_meta']['hostvars']['srv01'], {'cmk_site': 'test'})

    def test_log_entry_names_what_was_served(self):
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = [self._site('test', 'srv01')]
            syncer = self._syncer(MagicMock())
            syncer.get_full_inventory()
            self.assertEqual(syncer.name, "Checkmk Sites Inventory: 1 sites")
            syncer.get_host_inventory('srv01')
            self.assertEqual(syncer.name, "Checkmk Sites Inventory: srv01, site test")
            model.objects.return_value = []
            syncer.get_host_inventory('srv09')
            self.assertEqual(syncer.name, "Checkmk Sites Inventory: srv09 not found")

    def test_without_settings_sites_of_enabled_settings(self):
        enabled = [MagicMock()]
        with patch.object(site_syncer, 'CheckmkSite') as model, \
                patch.object(site_syncer, 'CheckmkSettings') as settings_model:
            settings_model.objects.return_value = enabled
            model.objects.return_value = []
            self._syncer().get_full_inventory()
        settings_model.objects.assert_called_once_with(enabled__ne=False)
        model.objects.assert_called_once_with(enabled=True, settings_master__in=enabled)

    def test_disabled_settings_have_no_sites(self):
        settings = MagicMock(enabled=False)
        with patch.object(site_syncer, 'CheckmkSite') as model:
            inventory = self._syncer(settings).get_full_inventory()
            self.assertFalse(self._syncer(settings).get_host_inventory('srv01'))
        model.objects.assert_not_called()
        self.assertEqual(inventory['all']['hosts'], [])

    def test_host_with_two_sites_does_not_crash(self):
        with patch.object(site_syncer, 'CheckmkSite') as model, \
                patch.object(site_syncer, 'CheckmkSettings') as settings_model:
            settings_model.objects.return_value = []
            model.objects.return_value = [self._site('prod', 'srv01'),
                                          self._site('test', 'srv01')]
            result = self._syncer().get_host_inventory('srv01')
        model.objects.assert_called_once_with(enabled=True, server_address='srv01',
                                              settings_master__in=[])
        self.assertEqual(result, {'cmk_site': 'test'})

    def test_unknown_host(self):
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = []
            self.assertFalse(self._syncer(MagicMock()).get_host_inventory('srv09'))


if __name__ == '__main__':
    unittest.main()
