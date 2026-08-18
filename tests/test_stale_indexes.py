"""
Tests for the stale-index registry.

MongoEngine never removes an index a model stopped declaring. A leftover
plain index only costs write throughput; a leftover *unique* one breaks
inserts, because once its field is gone every document indexes as null
and a unique index permits exactly one of those.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import MagicMock, patch

from tests import _load_real_module  # pylint: disable=no-name-in-module

stale_indexes = _load_real_module(
    'application.helpers.stale_indexes_under_test',
    'helpers/stale_indexes.py',
)


class RegisterTest(unittest.TestCase):

    def setUp(self):
        self._saved = list(stale_indexes._STALE_INDEXES)  # pylint: disable=protected-access

    def tearDown(self):
        stale_indexes._STALE_INDEXES[:] = self._saved  # pylint: disable=protected-access

    def test_the_shipped_entry_is_registered(self):
        self.assertIn(('host_inventory_tree', 'hostname_1'),
                      stale_indexes._STALE_INDEXES)  # pylint: disable=protected-access

    def test_registering_twice_keeps_one_entry(self):
        before = len(stale_indexes._STALE_INDEXES)  # pylint: disable=protected-access
        stale_indexes.register_stale_index('col', 'idx_1')
        stale_indexes.register_stale_index('col', 'idx_1')
        self.assertEqual(
            len(stale_indexes._STALE_INDEXES), before + 1)  # pylint: disable=protected-access


class DropTest(unittest.TestCase):

    def setUp(self):
        self._saved = list(stale_indexes._STALE_INDEXES)  # pylint: disable=protected-access
        stale_indexes._STALE_INDEXES[:] = []  # pylint: disable=protected-access

    def tearDown(self):
        stale_indexes._STALE_INDEXES[:] = self._saved  # pylint: disable=protected-access

    def _database(self, collections, indexes):
        collection = MagicMock()
        collection.index_information.return_value = indexes
        database = MagicMock()
        database.list_collection_names.return_value = collections
        database.__getitem__.return_value = collection
        return database, collection

    def test_existing_index_is_dropped_and_reported(self):
        stale_indexes.register_stale_index('col', 'idx_1')
        database, collection = self._database(['col'], {'_id_': {}, 'idx_1': {}})
        with patch.object(stale_indexes, 'get_db', return_value=database):
            dropped = list(stale_indexes.drop_stale_indexes())
        self.assertEqual(dropped, ['col.idx_1'])
        collection.drop_index.assert_called_once_with('idx_1')

    def test_already_dropped_index_is_a_noop(self):
        stale_indexes.register_stale_index('col', 'idx_1')
        database, collection = self._database(['col'], {'_id_': {}})
        with patch.object(stale_indexes, 'get_db', return_value=database):
            dropped = list(stale_indexes.drop_stale_indexes())
        self.assertEqual(dropped, [])
        collection.drop_index.assert_not_called()

    def test_missing_collection_is_skipped(self):
        # A feature that was never enabled has no collection to clean.
        stale_indexes.register_stale_index('never_created', 'idx_1')
        database, collection = self._database([], {})
        with patch.object(stale_indexes, 'get_db', return_value=database):
            dropped = list(stale_indexes.drop_stale_indexes())
        self.assertEqual(dropped, [])
        collection.drop_index.assert_not_called()


if __name__ == '__main__':
    unittest.main()
