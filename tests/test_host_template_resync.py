"""
Re-matching a CMDB template against the whole database.

Editing a template never re-assigns anything on its own — the operator
triggers it from the template list. Matching hosts gain the template;
losing it is a separate, explicitly chosen action, because a host may
carry the template because somebody assigned it by hand. The export
attribute cache goes with every change.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=protected-access
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from application.models.host_templates import (
    clear_consumer_cache, parse_cmdb_match, sync_template_assignment,
)


class _Query:
    """Stand-in for a mongoengine queryset that records what it got."""

    def __init__(self, store):
        self._store = store
        self._ids = []

    def filter(self, **kwargs):
        child = _Query(self._store)
        if '__raw__' in kwargs:
            child._ids = self._store['matching']  # pylint: disable=protected-access
        else:
            child._ids = self._store['assigned']  # pylint: disable=protected-access
        return child

    def only(self, *_fields):
        return self

    def scalar(self, *_fields):
        return list(self._ids)

    def update(self, **kwargs):
        self._store['updates'].append(kwargs)
        return len(self._ids)


class ParseCmdbMatchTest(unittest.TestCase):
    """application.models.host_templates.parse_cmdb_match"""

    def test_plain_pattern(self):
        self.assertEqual(parse_cmdb_match('env:prod'), ('env', 'prod'))

    def test_whitespace_is_stripped(self):
        self.assertEqual(parse_cmdb_match(' env : prod '), ('env', 'prod'))

    def test_value_may_contain_a_colon(self):
        self.assertEqual(parse_cmdb_match('url:http://x'), ('url', 'http://x'))

    def test_empty_value_is_allowed(self):
        self.assertEqual(parse_cmdb_match('env:'), ('env', ''))

    def test_unusable_patterns(self):
        for pattern in (None, '', 'env', ':prod', '  :prod'):
            self.assertIsNone(parse_cmdb_match(pattern), pattern)


class SyncTemplateAssignmentTest(unittest.TestCase):
    """application.models.host_templates.sync_template_assignment"""

    def _run(self, matching, assigned, cmdb_match='env:prod',
             remove_stale=False):
        store = {'matching': matching, 'assigned': assigned, 'updates': []}
        template = SimpleNamespace(id='tmpl1', cmdb_match=cmdb_match)
        host_cls = SimpleNamespace(objects=lambda **_kw: _Query(store))
        with patch('application.models.host.Host', host_cls):
            result = sync_template_assignment(template,
                                              remove_stale=remove_stale)
        return result, store['updates']

    def test_new_matches_get_the_template(self):
        result, updates = self._run(matching=['h1', 'h2'], assigned=[])
        self.assertEqual(result, (2, 0))
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['add_to_set__cmdb_templates'], 'tmpl1')

    def test_non_matching_hosts_keep_the_template_by_default(self):
        # The assignment may well be a manual one — dropping it is only
        # ever done when the operator asks for it.
        result, updates = self._run(matching=[], assigned=['h1'])
        self.assertEqual(result, (0, 0))
        self.assertEqual(updates, [])

    def test_remove_stale_takes_the_template_off_them(self):
        result, updates = self._run(matching=[], assigned=['h1'],
                                    remove_stale=True)
        self.assertEqual(result, (0, 1))
        self.assertEqual(updates[0]['pull__cmdb_templates'], 'tmpl1')

    def test_every_change_drops_the_attribute_cache(self):
        _result, updates = self._run(matching=['h1'], assigned=['h2'],
                                     remove_stale=True)
        self.assertEqual(len(updates), 2)
        for update in updates:
            self.assertEqual(update['set__cache'], {})

    def test_unchanged_assignments_write_nothing(self):
        result, updates = self._run(matching=['h1'], assigned=['h1'])
        self.assertEqual(result, (0, 0))
        self.assertEqual(updates, [])

    def test_template_without_a_pattern_is_left_alone(self):
        # Its assignments are manual — clearing them would be data loss,
        # even when the operator asked for the removing variant.
        result, updates = self._run(matching=[], assigned=['h1'],
                                    cmdb_match='', remove_stale=True)
        self.assertIsNone(result)
        self.assertEqual(updates, [])


class ClearConsumerCacheTest(unittest.TestCase):
    """application.models.host_templates.clear_consumer_cache"""

    def _run(self, document, created=False):
        store = {'matching': [], 'assigned': [], 'updates': []}
        cleared = []
        host_cls = SimpleNamespace(
            objects=lambda **_kw: _Query(store),
            clear_template_cache=lambda: cleared.append(True),
        )
        with patch('application.models.host.Host', host_cls):
            clear_consumer_cache(None, document, created=created)
        return store['updates'], cleared

    def test_saving_a_template_drops_the_consumers_cache(self):
        updates, cleared = self._run(
            SimpleNamespace(pk='tmpl1', object_type='template'))
        self.assertEqual(updates, [{'set__cache': {}}])
        self.assertTrue(cleared)

    def test_a_plain_host_save_is_ignored(self):
        updates, cleared = self._run(
            SimpleNamespace(pk='h1', object_type='host'))
        self.assertEqual(updates, [])
        self.assertFalse(cleared)

    def test_a_new_template_has_no_consumers_yet(self):
        updates, _cleared = self._run(
            SimpleNamespace(pk='tmpl1', object_type='template'), created=True)
        self.assertEqual(updates, [])


class TemplateOpenChangesTest(unittest.TestCase):
    """
    A template feeds its values into every host carrying it, so editing
    one counts for the open changes badge — the same way a rule edit
    does. Hosts and plain objects deliberately do not: they only ever
    invalidate their own cache.
    """

    @classmethod
    def setUpClass(cls):
        # pylint: disable=import-outside-toplevel
        from tests.test_api import import_host_module
        cls.mod = import_host_module()

    def _view(self, view_cls):
        """A view instance without Flask-Admin's constructor."""
        return object.__new__(view_cls)

    def test_saving_a_template_counts_a_change(self):
        mod = self.mod
        view = self._view(mod.TemplateModelView)
        with patch.object(mod, 'add_changes') as add_changes, \
             patch.object(mod.ObjectModelView, 'on_model_change'), \
             patch.object(mod, 'flash'):
            mod.TemplateModelView.on_model_change(
                view, MagicMock(), MagicMock(), False)
        add_changes.assert_called_once()

    def test_deleting_a_template_counts_a_change(self):
        mod = self.mod
        view = self._view(mod.TemplateModelView)
        with patch.object(mod, 'add_changes') as add_changes, \
             patch.object(mod.ObjectModelView, 'on_model_delete',
                          create=True):
            mod.TemplateModelView.on_model_delete(view, MagicMock())
        add_changes.assert_called_once()

    def _bulk_lifecycle(self, view_cls, state_changed):
        mod = self.mod
        view = self._view(view_cls)
        template = MagicMock()
        template.set_lifecycle_state.return_value = state_changed
        with patch.object(mod, 'add_changes') as add_changes, \
             patch.object(mod, 'Host') as host_cls, \
             patch.object(mod, 'flash'), \
             patch.object(mod, 'redirect'), \
             patch.object(mod, 'url_for'), \
             patch.object(mod, 'request'):
            host_cls.objects.return_value = [template]
            view_cls._bulk_set_lifecycle(view, ['id1'], 'archived')
        return add_changes

    def test_archiving_a_template_counts_a_change(self):
        add_changes = self._bulk_lifecycle(self.mod.TemplateModelView, True)
        add_changes.assert_called_once()

    def test_a_bulk_action_that_moved_nothing_counts_nothing(self):
        add_changes = self._bulk_lifecycle(self.mod.TemplateModelView, False)
        add_changes.assert_not_called()

    def test_archiving_a_plain_host_counts_nothing(self):
        add_changes = self._bulk_lifecycle(self.mod.HostModelView, True)
        add_changes.assert_not_called()
