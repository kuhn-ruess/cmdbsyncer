"""Tests for the duplicate clustering of the Data Quality dashboard."""
# pylint: disable=missing-function-docstring,missing-class-docstring

import unittest

from application.views.data_quality import _duplicate_clusters


def _member(name, archived=False):
    return {'name': name, 'archived': archived}


class DuplicateClusterTests(unittest.TestCase):
    def test_two_live_hosts_are_a_duplicate(self):
        clusters = _duplicate_clusters({
            'web01': [_member('WEB01'), _member('web01.example.com')],
        })
        self.assertEqual(len(clusters), 1)
        self.assertEqual([m['name'] for m in clusters[0]],
                         ['WEB01', 'web01.example.com'])

    def test_archived_partner_is_no_duplicate(self):
        # The archived twin is the normal result of a rename/replacement.
        clusters = _duplicate_clusters({
            'web01': [_member('WEB01'), _member('web01', archived=True)],
        })
        self.assertEqual(clusters, [])

    def test_only_archived_is_no_duplicate(self):
        clusters = _duplicate_clusters({
            'web01': [_member('WEB01', archived=True),
                      _member('web01', archived=True)],
        })
        self.assertEqual(clusters, [])

    def test_archived_rides_along_on_a_real_duplicate(self):
        clusters = _duplicate_clusters({
            'web01': [_member('web01.example.com'),
                      _member('old-web01', archived=True),
                      _member('WEB01')],
        })
        self.assertEqual(len(clusters), 1)
        # Live members first (alphabetically), archived last.
        self.assertEqual([m['name'] for m in clusters[0]],
                         ['WEB01', 'web01.example.com', 'old-web01'])

    def test_single_host_is_no_duplicate(self):
        self.assertEqual(_duplicate_clusters({'web01': [_member('WEB01')]}), [])

    def test_bigger_clusters_come_first(self):
        clusters = _duplicate_clusters({
            'a': [_member('A1'), _member('a1')],
            'b': [_member('B1'), _member('b1'), _member('b1.example.com')],
        })
        self.assertEqual([len(c) for c in clusters], [3, 2])


if __name__ == '__main__':
    unittest.main()
