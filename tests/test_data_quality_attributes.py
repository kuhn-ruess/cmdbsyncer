"""
Unit tests for Data Quality: Attribute Values. The aggregation pipeline and
the shaping of its result, no Mongo needed.
"""
# pylint: disable=missing-function-docstring
import re
import unittest

from application.views.data_quality_attributes import (
    attribute_values, build_pipeline, filter_value, name_regex, overview)


def _row(key, value, hosts):
    return {'_id': {'k': key, 'v': value}, 'hosts': hosts}


class TestNameRegex(unittest.TestCase):
    """name_regex"""

    def test_modes(self):
        self.assertIsNone(name_regex('  ', 'prefix'))
        self.assertEqual(name_regex('cmdb_', 'prefix'), '^cmdb_')
        self.assertEqual(name_regex('a.b', 'exact'), r'^a\.b$')
        self.assertTrue(re.match(name_regex('OS', 'exact'), 'os', re.I))


class TestPipeline(unittest.TestCase):
    """build_pipeline"""

    def test_overview_groups_twice(self):
        pipeline = build_pipeline('labels', None, False)
        self.assertEqual(pipeline[0]['$match'],
                         {'is_object': {'$ne': True}, 'deleted_at': {'$exists': False}})
        self.assertEqual(pipeline[1]['$project']['kv'],
                         {'$objectToArray': {'$ifNull': ['$labels', {}]}})
        self.assertEqual([list(stage)[0] for stage in pipeline],
                         ['$match', '$project', '$unwind', '$group', '$group'])

    def test_values_filtered_by_key(self):
        pipeline = build_pipeline('inventory', '^os', True)
        self.assertEqual(pipeline[3], {'$match': {'kv.k': {'$regex': '^os',
                                                           '$options': 'i'}}})
        self.assertEqual(list(pipeline[-1]), ['$group'])
        self.assertEqual(pipeline[-1]['$group']['_id'], {'k': '$kv.k', 'v': '$kv.v'})


class TestFilterValue(unittest.TestCase):
    """filter_value"""

    def test_values(self):
        self.assertEqual(filter_value('os', 'Linux 9'), r'os:^Linux\ 9$')
        self.assertEqual(filter_value('os', None), 'os:none')
        self.assertEqual(filter_value('flag', True), 'flag:yes')
        self.assertEqual(filter_value('vlan', 5), 'vlan:^5$')
        self.assertIsNone(filter_value('ips', ['192.0.2.1']))
        self.assertIsNone(filter_value('bad key', 'x'))
        self.assertIsNone(filter_value('os', 'x' * 20000))


class TestShaping(unittest.TestCase):
    """overview / attribute_values"""

    def test_overview_sorted(self):
        rows = overview([{'_id': 'os', 'hosts': 3, 'values': 2},
                         {'_id': 'Location', 'hosts': 1, 'values': 1}])
        self.assertEqual([r['name'] for r in rows], ['Location', 'os'])
        self.assertEqual(rows[1], {'name': 'os', 'hosts': 3, 'distinct': 2})

    def test_values_counts_variants_and_limit(self):
        attrs = attribute_values([
            _row('os', 'linux', 5), _row('os', 'Linux ', 2),
            _row('os', 'windows', 7), _row('os', None, 1),
            _row('env', 'prod', 1)], limit=3)
        self.assertEqual([a['name'] for a in attrs], ['env', 'os'])
        os_attr = attrs[1]
        self.assertEqual((os_attr['hosts'], os_attr['distinct'], os_attr['hidden']),
                         (15, 4, 1))
        self.assertEqual([(v['display'], v['hosts'], v['variant'])
                          for v in os_attr['values']],
                         [('windows', 7, False), ('linux', 5, True),
                          ('Linux ', 2, True)])

    def test_no_limit_and_empty(self):
        attr = attribute_values([_row('os', '', 2), _row('os', None, 1)],
                                limit=None)[0]
        self.assertEqual(attr['hidden'], 0)
        self.assertEqual([(v['empty'], v['variant']) for v in attr['values']],
                         [(True, True), (True, True)])
        attr = attribute_values([_row('vlan', 5, 1), _row('vlan', '5', 1),
                                 _row('vlan', 6, 1)])[0]
        self.assertEqual([v['variant'] for v in attr['values']],
                         [True, True, False])


if __name__ == '__main__':
    unittest.main()
