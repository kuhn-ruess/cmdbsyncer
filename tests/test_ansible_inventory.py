"""
Ansible inventory: one save per host, the cached attribute set stays
untouched, and every project caches into its own slots.
"""
# pylint: disable=missing-function-docstring,protected-access
import os
import unittest
from unittest.mock import MagicMock

from tests import _load_real_module  # pylint: disable=no-name-in-module

inventory = _load_real_module(
    "application.plugins.ansible.inventory",
    os.path.join("plugins", "ansible", "inventory.py"),
)


def _host():
    db_host = MagicMock()
    db_host.hostname = 'host1'
    db_host.cache = {}
    return db_host


def _syncer(filtered, outcomes, cache_key='ansible'):
    syncer = inventory.AnsibleInventory()
    syncer.cache_key = cache_key
    syncer.get_attributes = MagicMock(
        return_value={'all': {'a': '1'}, 'filtered': filtered})
    syncer.actions = MagicMock()
    syncer.actions.get_outcomes.return_value = outcomes
    return syncer


class TestHostVars(unittest.TestCase):
    """AnsibleInventory.get_host_vars"""

    def test_merges_filtered_and_variables(self):
        filtered = {'a': '1', 'flag': 'true'}
        syncer = _syncer(filtered, {'ansible_user': 'root'})
        self.assertEqual(syncer.get_host_vars(_host()),
                         {'a': '1', 'flag': True, 'ansible_user': 'root'})
        # The filtered set is the one in the host's cache
        self.assertEqual(filtered, {'a': '1', 'flag': 'true'})

    def test_collects_cache_writes_into_one_save(self):
        db_host = _host()
        syncer = _syncer({}, {}, cache_key='ansible_Project')
        db_host._cache_dirty = True
        syncer.get_host_vars(db_host)
        syncer.get_attributes.assert_called_once_with(
            db_host, 'ansible_Project', persist_cache=False)
        syncer.actions.get_outcomes.assert_called_once_with(
            db_host, {'a': '1'}, persist_cache=False)
        db_host.save.assert_called_once_with()

    def test_dropped_host(self):
        syncer = _syncer({}, {'ignore_host': True})
        self.assertIs(syncer.get_host_vars(_host()), False)
        syncer.get_attributes.return_value = False
        self.assertIs(syncer.get_host_vars(_host()), False)


if __name__ == '__main__':
    unittest.main()
