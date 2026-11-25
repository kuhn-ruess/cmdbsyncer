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
from application.plugins.checkmk import editions  # pylint: disable=wrong-import-position


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



class BakeAgentsTest(unittest.TestCase):
    """Only the site marked as central gets the bake step and the key."""

    def test_unmarked_site_does_not_bake(self):
        site = MagicMock(bake_agents_after_update=False)
        self.assertEqual(site_syncer.SyncSites.bake_agents(site), {})

    def test_marked_site_gets_the_key(self):
        site = MagicMock(bake_agents_after_update=True)
        site.settings_master.bakery_key_id = ' {{ACCOUNT:bakery:key}} '
        site.settings_master.bakery_passphrase = '{{ACCOUNT:bakery:password}}'
        rendered = {' {{ACCOUNT:bakery:key}} ': ' 2 ',
                    '{{ACCOUNT:bakery:password}}': 'secret'}
        with patch.object(site_syncer, 'render_jinja', side_effect=rendered.get):
            self.assertEqual(site_syncer.SyncSites.bake_agents(site), {
                'cmk_bake_agents': True, 'cmk_bakery_key_id': '2',
                'cmk_bakery_passphrase': 'secret'})


class EditionForVersionTest(unittest.TestCase):
    """Checkmk 2.5 renamed the editions: a 2.5 site with the settings on
    cee failed with "Version 2.5.0p21.cee is not installed"."""

    def test_renamed_both_ways(self):
        for edition, version, expected in (
                ('cee', '2.5.0p21', 'pro'), ('cre', '2.5.0', 'community'),
                ('cce', '2.6.0p1', 'ultimate'), ('cme', '2.5.0p1', 'ultimatemt'),
                ('pro', '2.4.0p12', 'cee'), ('ultimatemt', '2.3.0p1', 'cme'),
                ('pro', '2.5.0p21', 'pro'), ('cee', '2.4.0p12', 'cee'),
                ('cee', '', 'cee'), ('cee', None, 'cee'), (None, '2.5.0', None)):
            with self.subTest(edition=edition, version=version):
                self.assertEqual(editions.edition_for_version(edition, version), expected)

    def test_inventory_hands_the_fitting_edition(self):
        site = MagicMock(custom_ansible_variables=[], bake_agents_after_update=False)
        site.name, site.server_address = 'mysite', 'srv01'
        site.settings_master.cmk_edition = 'cee'
        site.settings_master.cmk_version = '2.5.0p21'
        site.settings_master.pre_update_url = ''
        with patch.object(site_syncer, 'render_jinja',
                          side_effect=lambda text, **kwargs: text if not kwargs
                          else f"{kwargs['CMK_EDITION']}-{kwargs['CMK_VERSION']}"):
            data = site_syncer.SyncSites.__new__(site_syncer.SyncSites).get_site_data(site)
        self.assertEqual(data['cmk_edition'], 'pro')
        self.assertEqual(data['cmk_version_filename'], 'pro-2.5.0p21')


if __name__ == '__main__':
    unittest.main()
