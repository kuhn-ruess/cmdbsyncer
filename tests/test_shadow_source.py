"""
Shadow source accounts: an import that only stores its labels next to
the live ones, and debug runs that evaluate the rules with them.
"""
import unittest
from unittest.mock import Mock

from application.helpers.import_hostnames import update_import_host
from application.helpers.shadow_data import (shadow_diff, shadow_view,
                                             shadow_view_active)
from application.modules.plugin import Plugin


class UpdateImportHostShadowTest(unittest.TestCase):
    """The import path of a shadow source account"""

    def test_a_shadow_source_only_stores_shadow_labels(self):
        """Owner, labels and the document stay untouched"""
        host = Mock()
        host.update_shadow.return_value = True
        config = {'name': 'new_cmdb', 'shadow_mode': True}
        self.assertTrue(update_import_host(host, {'a': 1}, config, import_id='x'))
        host.update_shadow.assert_called_once_with({'a': 1}, config)
        host.update_host.assert_not_called()
        host.set_account.assert_not_called()
        host.save.assert_not_called()

    def test_an_unknown_host_is_reported_as_not_saved(self):
        """A host the syncer does not know is not created"""
        host = Mock()
        host.update_shadow.return_value = False
        self.assertFalse(update_import_host(host, {}, {'name': 'n', 'shadow_mode': True}))

    def test_a_normal_account_is_not_affected(self):
        """Without shadow mode the import works as before"""
        host = Mock()
        host.set_account.return_value = True
        update_import_host(host, {'a': 1}, {'name': 'old', 'shadow_mode': False})
        host.update_shadow.assert_not_called()
        host.update_host.assert_called_once_with({'a': 1})


class ShadowViewTest(unittest.TestCase):
    """Which labels the attributes are built from"""

    @staticmethod
    def _host():
        host = Mock()
        host.labels = {'site': 'Berlin'}
        host.source_account_name = 'old'
        host.shadow_labels = {'site': 'Frankfurt'}
        host.shadow_account_name = 'new'
        return host

    def test_live_labels_outside_the_view(self):
        """Exports always see the live labels"""
        self.assertFalse(shadow_view_active())
        self.assertEqual(Plugin._host_source(self._host()),  # pylint: disable=protected-access
                         ('old', {'site': 'Berlin'}))

    def test_shadow_labels_inside_the_view(self):
        """A debug run sees the shadow labels"""
        with shadow_view():
            self.assertTrue(shadow_view_active())
            self.assertEqual(Plugin._host_source(self._host()),  # pylint: disable=protected-access
                             ('new', {'site': 'Frankfurt'}))
        self.assertFalse(shadow_view_active())

    def test_the_view_ends_even_when_the_run_fails(self):
        """A failing debug run must not leave later runs on shadow labels"""
        with self.assertRaises(RuntimeError):
            with shadow_view():
                raise RuntimeError('boom')
        self.assertFalse(shadow_view_active())


class ShadowDiffTest(unittest.TestCase):
    """The comparison of live and shadow values"""

    def test_only_differing_keys_sorted(self):
        """Equal values are left out, a missing side is None"""
        live = {'b': 1, 'a': 'x', 'same': True}
        shadow = {'b': 2, 'c': 'new', 'same': True}
        self.assertEqual(shadow_diff(live, shadow), [
            ('a', 'x', None),
            ('b', 1, 2),
            ('c', None, 'new'),
        ])

    def test_missing_sides_count_as_empty(self):
        """No dict on one side compares like an empty one"""
        self.assertEqual(shadow_diff(None, {'a': 1}), [('a', None, 1)])
        self.assertEqual(shadow_diff({}, {}), [])


if __name__ == '__main__':
    unittest.main()
