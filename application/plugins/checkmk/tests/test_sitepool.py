"""
Unit tests for checkmk sitepool module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.rules import CheckmkRule
from application.plugins.checkmk.inits import reset_sitepools, pool_sticky_notes
from application.plugins.checkmk.sitepool import (
    get_site,
    release_site,
    release_site_for_site_id,
)


def _member(site_id, hosts_taken):
    member = Mock()
    member.site_id = site_id
    member.hosts_taken = hosts_taken
    return member


class TestGetSite(unittest.TestCase):
    """Tests for get_site"""

    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_picks_least_loaded_site(self, mock_pool):
        pool = Mock()
        pool.member_sites = [
            _member('berlin_1', 2),
            _member('berlin_2', 0),
            _member('berlin_3', 1),
        ]
        mock_pool.objects.get.return_value = pool
        mock_pool.objects.return_value.update_one.return_value = 1

        result = get_site('berlin')
        # berlin_2 has the fewest hosts -> it wins
        self.assertEqual(result, 'berlin_2')
        mock_pool.objects.assert_called_with(
            name='berlin',
            member_sites__site_id='berlin_2',
            member_sites__hosts_taken=0,
        )

    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_retries_on_lost_race(self, mock_pool):
        pool = Mock()
        pool.member_sites = [_member('berlin_1', 0)]
        mock_pool.objects.get.return_value = pool
        # First guarded update loses the race (0), second wins (1).
        mock_pool.objects.return_value.update_one.side_effect = [0, 1]

        result = get_site('berlin')
        self.assertEqual(result, 'berlin_1')
        self.assertEqual(
            mock_pool.objects.return_value.update_one.call_count, 2)

    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_returns_false_when_pool_missing(self, mock_pool):
        mock_pool.objects.get.side_effect = DoesNotExist()
        self.assertFalse(get_site('nope'))

    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_returns_false_when_no_members(self, mock_pool):
        pool = Mock()
        pool.member_sites = []
        mock_pool.objects.get.return_value = pool
        self.assertFalse(get_site('empty'))


class TestReleaseSite(unittest.TestCase):
    """Tests for release_site"""

    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_decrements_guarded(self, mock_pool):
        release_site('berlin', 'berlin_1')
        mock_pool.objects.assert_called_once_with(
            name='berlin',
            member_sites__site_id='berlin_1',
            member_sites__hosts_taken__gt=0,
        )
        mock_pool.objects.return_value.update_one.assert_called_once_with(
            dec__member_sites__S__hosts_taken=1)


class TestReleaseSiteForSiteId(unittest.TestCase):
    """Tests for release_site_for_site_id"""

    @patch('application.plugins.checkmk.sitepool.release_site')
    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_finds_pool_and_releases(self, mock_pool, mock_release):
        pool = Mock()
        pool.name = 'berlin'
        mock_pool.objects.return_value.first.return_value = pool

        release_site_for_site_id('berlin_1')
        mock_release.assert_called_once_with('berlin', 'berlin_1')

    @patch('application.plugins.checkmk.sitepool.release_site')
    @patch('application.plugins.checkmk.sitepool.CheckmkSitePool')
    def test_no_pool_no_release(self, mock_pool, mock_release):
        mock_pool.objects.return_value.first.return_value = None
        release_site_for_site_id('berlin_1')
        mock_release.assert_not_called()


class TestSitePoolStickyRule(unittest.TestCase):
    """The site_pool rule action keeps a host on its assigned site (sticky)."""

    def setUp(self):
        with patch('application.plugins.checkmk.rules.Rule.__init__',
                   return_value=None):
            self.rule = CheckmkRule()
            self.rule.debug = False
            self.rule.attributes = {}

    @patch('application.plugins.checkmk.rules.sitepool')
    def test_sticky_reuses_existing_site(self, mock_sitepool):
        db_host = Mock()
        db_host.get_pool_site.return_value = 'berlin_2'
        self.rule.db_host = db_host

        outcomes = {'custom_attributes': {}}
        rule_outcomes = [{'action': 'site_pool', 'action_param': 'berlin'}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)

        # Keeps its site, no new allocation.
        self.assertEqual(result['custom_attributes']['site'], 'berlin_2')
        mock_sitepool.get_site.assert_not_called()
        self.assertTrue(self.rule.found_sitepool_rule)

    @patch('application.plugins.checkmk.rules.sitepool')
    def test_allocates_when_unassigned(self, mock_sitepool):
        db_host = Mock()
        db_host.get_pool_site.return_value = False
        db_host.hostname = 'srv1'
        self.rule.db_host = db_host
        mock_sitepool.get_site.return_value = 'berlin_1'

        outcomes = {'custom_attributes': {}}
        rule_outcomes = [{'action': 'site_pool', 'action_param': 'berlin'}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)

        self.assertEqual(result['custom_attributes']['site'], 'berlin_1')
        db_host.lock_to_pool_site.assert_called_once_with('berlin_1')


class TestPoolStickyNotes(unittest.TestCase):
    """The debug output tells that pool assignments are sticky"""

    def test_notes_for_both_pools(self):
        db_host = Mock()
        db_host.get_folder.return_value = '/pool1'
        db_host.get_pool_site.return_value = 'berlin_2'

        notes = pool_sticky_notes(db_host)

        self.assertIn('/pool1', notes['Folder Pool (sticky)'])
        self.assertIn('reset_folderpools', notes['Folder Pool (sticky)'])
        self.assertIn('berlin_2', notes['Site Pool (sticky)'])
        self.assertIn('reset_sitepools', notes['Site Pool (sticky)'])

    def test_no_notes_without_assignment(self):
        db_host = Mock()
        db_host.get_folder.return_value = False
        db_host.get_pool_site.return_value = False
        self.assertEqual(pool_sticky_notes(db_host), {})


class TestResetSitePools(unittest.TestCase):
    """Tests for reset_sitepools"""

    @patch('application.plugins.checkmk.inits.CheckmkSitePool')
    @patch('application.plugins.checkmk.inits.Host')
    def test_clears_assignments_counters_and_cache(self, mock_host, mock_pool):
        pool = Mock()
        pool.name = 'berlin'
        pool.member_sites = [_member('berlin_1', 5), _member('berlin_2', 3)]
        mock_pool.objects.return_value = [pool]

        reset_sitepools()

        # Sticky assignment dropped and rule caches invalidated, otherwise
        # the cached outcome would carry the old site into the next export.
        mock_host.objects.assert_any_call(pool_site__ne=None)
        mock_host.objects.return_value.update.assert_any_call(unset__pool_site=1)
        mock_host.objects.assert_any_call(cache__ne={})
        mock_host.objects.return_value.update.assert_any_call(set__cache={})

        for member in pool.member_sites:
            self.assertEqual(member.hosts_taken, 0)
        pool.save.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
