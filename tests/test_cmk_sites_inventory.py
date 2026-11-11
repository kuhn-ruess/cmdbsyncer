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

    def test_without_settings_all_enabled_sites(self):
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = []
            self._syncer().get_full_inventory()
        model.objects.assert_called_once_with(enabled=True)

    def test_host_with_two_sites_does_not_crash(self):
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = [self._site('prod', 'srv01'),
                                          self._site('test', 'srv01')]
            result = self._syncer().get_host_inventory('srv01')
        model.objects.assert_called_once_with(enabled=True, server_address='srv01')
        self.assertEqual(result, {'cmk_site': 'test'})

    def test_unknown_host(self):
        with patch.object(site_syncer, 'CheckmkSite') as model:
            model.objects.return_value = []
            self.assertFalse(self._syncer(MagicMock()).get_host_inventory('srv09'))


if __name__ == '__main__':
    unittest.main()
