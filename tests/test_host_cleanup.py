"""
Tests for the side-document cleanup that runs on every host deletion.

Three stores hang off a Host without a MongoEngine delete rule to reach
them: the inventory trees and field approvals (keyed by hostname as a
plain string) and the inbound relation edges (a reference inside an
embedded document). These tests pin that all three are handled, and that
the hook sits on the queryset rather than on a delete signal — a signal
receiver makes MongoEngine fall back to a per-document loop for every
bulk delete.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=protected-access
import sys
import types
import unittest
from unittest.mock import MagicMock, patch



class _FieldApproval:  # pylint: disable=too-few-public-methods
    objects = MagicMock()


_fa_module = types.ModuleType('application.models.field_approval')
_fa_module.FieldApproval = _FieldApproval
sys.modules['application.models.field_approval'] = _fa_module

# Imported after the FieldApproval stub above so the module under test
# resolves against it.
# pylint: disable=wrong-import-position
from application.models import host_cleanup                   # noqa: E402
from application.models.host import Host                      # noqa: E402
from application.models.host_inventory_tree import (          # noqa: E402
    HostInventoryTree,
)


class _StubQuerySet(host_cleanup.HostQuerySet):
    """HostQuerySet with the parts that would talk to MongoDB replaced."""

    def __init__(self, hosts):  # pylint: disable=super-init-not-called
        self._hosts = hosts

    def clone(self):
        return self

    def only(self, *fields):  # pylint: disable=unused-argument
        return self

    def __iter__(self):
        return iter(self._hosts)


def _host(pk, hostname):
    return types.SimpleNamespace(pk=pk, hostname=hostname)


class PurgeSideDocumentsTest(unittest.TestCase):

    def setUp(self):
        for model in (Host, HostInventoryTree, _FieldApproval):
            model.objects.reset_mock()

    def test_inventory_trees_are_deleted_by_hostname(self):
        host_cleanup._purge_side_documents(['id1'], ['host-a', 'host-b'])
        HostInventoryTree.objects.assert_called_once_with(
            hostname__in=['host-a', 'host-b'])
        HostInventoryTree.objects.return_value.delete.assert_called_once_with()

    def test_pending_approvals_are_rejected_not_deleted(self):
        # Deleting them would drop the decision trail; rejecting lets the
        # existing TTL on decided entries clear them on schedule.
        host_cleanup._purge_side_documents(['id1'], ['host-a'])
        _FieldApproval.objects.assert_called_once_with(
            hostname__in=['host-a'], status='pending')
        update = _FieldApproval.objects.return_value.update
        self.assertEqual(update.call_count, 1)
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs['set__status'], 'rejected')
        self.assertEqual(kwargs['set__decision_reason'], 'Host was deleted')
        self.assertIn('set__decided_at', kwargs)
        _FieldApproval.objects.return_value.delete.assert_not_called()

    def test_inbound_relation_edges_are_pulled(self):
        host_cleanup._purge_side_documents(['id1', 'id2'], ['host-a'])
        Host.objects.assert_called_once_with(
            __raw__={'relations.target_host': {'$in': ['id1', 'id2']}})
        Host.objects.return_value.update.assert_called_once_with(
            __raw__={'$pull': {'relations': {
                'target_host': {'$in': ['id1', 'id2']}}}})

    def test_nothing_runs_without_matches(self):
        host_cleanup._purge_side_documents([], [])
        HostInventoryTree.objects.assert_not_called()
        _FieldApproval.objects.assert_not_called()
        Host.objects.assert_not_called()


class HostQuerySetDeleteTest(unittest.TestCase):

    def test_keys_are_collected_before_the_documents_are_gone(self):
        queryset = _StubQuerySet([_host('id1', 'host-a'), _host('id2', 'host-b')])
        order = []
        with patch.object(host_cleanup.QuerySet, 'delete',
                          side_effect=lambda *a, **kw: order.append('delete') or 2), \
             patch.object(host_cleanup, '_purge_side_documents',
                          side_effect=lambda *a: order.append('purge')) as purge:
            result = queryset.delete()
        self.assertEqual(result, 2)
        self.assertEqual(order, ['delete', 'purge'])
        purge.assert_called_once_with(['id1', 'id2'], ['host-a', 'host-b'])

    def test_empty_queryset_skips_the_purge(self):
        queryset = _StubQuerySet([])
        with patch.object(host_cleanup.QuerySet, 'delete', return_value=0), \
             patch.object(host_cleanup, '_purge_side_documents') as purge:
            queryset.delete()
        purge.assert_not_called()

    def test_delete_arguments_are_passed_through(self):
        queryset = _StubQuerySet([_host('id1', 'host-a')])
        with patch.object(host_cleanup.QuerySet, 'delete',
                          return_value=1) as base_delete, \
             patch.object(host_cleanup, '_purge_side_documents'):
            queryset.delete(write_concern={'w': 2})
        base_delete.assert_called_once_with(write_concern={'w': 2})


class RelationTargetTest(unittest.TestCase):
    """
    Databases written before the queryset cleanup still carry references
    to deleted hosts. MongoEngine raises on dereferencing one instead of
    returning None, so `if not rel.target_host` never gets to run — the
    line setting up the check has already raised.
    """

    def test_returns_the_target_when_it_exists(self):
        target = _host('id1', 'host-a')
        relation = types.SimpleNamespace(target_host=target)
        self.assertIs(host_cleanup.relation_target(relation), target)

    def test_returns_none_for_a_deleted_target(self):
        class _Dangling:  # pylint: disable=too-few-public-methods
            @property
            def target_host(self):
                raise host_cleanup.DoesNotExist('deleted')

        self.assertIsNone(host_cleanup.relation_target(_Dangling()))

    def test_other_errors_are_not_swallowed(self):
        class _Broken:  # pylint: disable=too-few-public-methods
            @property
            def target_host(self):
                raise ValueError('something else')

        with self.assertRaises(ValueError):
            host_cleanup.relation_target(_Broken())


class HookLocationTest(unittest.TestCase):
    """
    MongoEngine turns ``Host.objects(...).delete()`` into a per-document
    Python loop as soon as the class has a pre/post_delete receiver
    (queryset/base.py, ``call_document_delete``). The cleanup therefore
    has to hang off the queryset, not off a signal.
    """

    def test_delete_is_overridden_on_the_queryset(self):
        self.assertIn('delete', host_cleanup.HostQuerySet.__dict__)

    def test_module_connects_no_signal_receivers(self):
        self.assertFalse(
            [name for name in dir(host_cleanup) if 'signal' in name.lower()])


if __name__ == '__main__':
    unittest.main()
