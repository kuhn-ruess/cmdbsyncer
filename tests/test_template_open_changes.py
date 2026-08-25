"""
Editing a CMDB template counts for the open changes badge.

A template feeds its values into every host carrying it, so changing one
is a configuration change like a rule edit. Hosts and plain objects
deliberately do not count: they only ever invalidate their own cache.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=protected-access
import unittest
from unittest.mock import MagicMock, patch


class TemplateOpenChangesTest(unittest.TestCase):

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
             patch.object(mod, 'Host'):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
