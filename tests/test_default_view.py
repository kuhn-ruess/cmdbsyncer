"""Regression tests for shared admin view helpers."""

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stub_module(name, **attrs):
    # Augment an existing stub module if one is already registered — replacing
    # it wholesale would wipe out attributes set by tests/__init__.py (e.g.
    # mongoengine.errors.DoesNotExist) and break later tests.
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class _BaseModelView:
    """Minimal parent class used to observe super() calls."""

    def on_model_change(self, form, model, is_created):
        """Return the call arguments so tests can assert on them."""
        return {"form": form, "model": model, "created": is_created}

    def is_action_allowed(self, _name):
        """Flask-Admin allows every action it knows by default."""
        return True


class _EndpointLinkRowAction:  # pylint: disable=too-few-public-methods
    """Simple placeholder matching Flask-Admin's constructor shape."""

    def __init__(self, *_args, **_kwargs):
        pass


_MODULE = None


def _load_default_module():
    """Load the real module under lightweight import stubs, once."""
    global _MODULE  # pylint: disable=global-statement
    if _MODULE is not None:
        return _MODULE
    _stub_module(
        "flask",
        url_for=lambda *a, **k: "",
        redirect=lambda x: x,
        flash=lambda *a, **k: None,
        request=types.SimpleNamespace(),
    )
    _stub_module(
        "flask_login",
        current_user=types.SimpleNamespace(is_authenticated=True),
    )
    _stub_module(
        "application.helpers.sates",
        add_changes=lambda num=1: None,
    )
    _stub_module(
        "application.models.user",
        is_readonly=lambda user: False,
    )
    _stub_module(
        "flask_admin",
        AdminIndexView=object,
        expose=lambda *a, **k: (lambda fn: fn),
    )
    _stub_module(
        "flask_admin.contrib.mongoengine",
        ModelView=_BaseModelView,
    )
    _stub_module(
        "flask_admin.actions",
        action=lambda *_a, **_k: (lambda fn: fn),
    )
    _stub_module(
        "flask_admin.model.template",
        EndpointLinkRowAction=_EndpointLinkRowAction,
    )
    _stub_module(
        "flask_admin.helpers",
        get_redirect_target=lambda: "",
        is_safe_url=lambda target: True,
    )
    _stub_module(
        "flask_admin.model.helpers",
        get_mdict_item_or_list=lambda data, key: data.get(key),
    )
    _stub_module(
        "mongoengine.errors",
        NotUniqueError=type("NotUniqueError", (Exception,), {}),
    )
    _stub_module(
        "wtforms.validators",
        ValidationError=type("ValidationError", (Exception,), {}),
    )
    _stub_module("application._version", __version__="1.2.3")

    spec = importlib.util.spec_from_file_location(
        "application.views.default",
        os.path.join(REPO_ROOT, "application", "views", "default.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["application.views.default"] = module
    spec.loader.exec_module(module)
    _MODULE = module
    return _MODULE


class DefaultViewModelChangeTest(unittest.TestCase):
    """Verify DefaultModelView model normalization behavior."""

    @classmethod
    def setUpClass(cls):
        cls.default_module = _load_default_module()

    def test_on_model_change_trims_all_string_fields_before_super_call(self):
        """String fields are trimmed before delegating to the parent view."""
        class Model:  # pylint: disable=too-few-public-methods
            """Simple object with mixed field types."""

            alpha = "  one  "
            beta = "  two  "
            count = 3

        model = Model()
        view = self.default_module.DefaultModelView.__new__(
            self.default_module.DefaultModelView
        )

        with patch.object(
            _BaseModelView,
            "on_model_change",
            return_value="saved",
        ) as mocked_super:
            result = self.default_module.DefaultModelView.on_model_change(
                view, None, model, False
            )

        self.assertEqual(result, "saved")
        self.assertEqual(model.alpha, "one")
        self.assertEqual(model.beta, "two")
        self.assertEqual(model.count, 3)
        mocked_super.assert_called_once_with(None, model, False)


class _FakeDoc:  # pylint: disable=too-few-public-methods
    """Rule stand-in that records whether it was written."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.saved = 0

    def save(self):
        """Count the writes instead of touching a database."""
        self.saved += 1


class BulkEnableDisableTest(unittest.TestCase):
    """The Enable / Disable bulk actions of every list view."""

    @classmethod
    def setUpClass(cls):
        cls.default_module = _load_default_module()

    def _view(self, docs, fields=('name', 'enabled')):
        """A view instance whose model yields *docs* and knows *fields*."""
        view = self.default_module.DefaultModelView.__new__(
            self.default_module.DefaultModelView
        )
        view.model = types.SimpleNamespace(_fields=dict.fromkeys(fields))
        view.object_id_converter = str
        view.get_query = lambda: types.SimpleNamespace(
            in_bulk=lambda _ids: dict(enumerate(docs)))
        view.bulk_calls = 0
        view.on_bulk_change = lambda: setattr(
            view, 'bulk_calls', view.bulk_calls + 1)
        return view

    def _run(self, view, enabled, ids=('1',)):
        module = self.default_module
        with patch.object(module, 'request',
                          types.SimpleNamespace(referrer='/back')), \
             patch.object(module, 'add_changes') as add_changes, \
             patch.object(module, 'flash') as flash:
            module.DefaultModelView._bulk_set_enabled(  # pylint: disable=protected-access
                view, list(ids), enabled)
        return add_changes, flash

    def test_disable_writes_only_what_changes(self):
        """Only entries that differ are written."""
        docs = [_FakeDoc(True), _FakeDoc(False), _FakeDoc(None)]
        view = self._view(docs)
        self._run(view, False)
        self.assertEqual([doc.enabled for doc in docs], [False, False, None])
        self.assertEqual([doc.saved for doc in docs], [1, 0, 0])

    def test_enable_switches_the_selection_on(self):
        """Off and unset entries both come on."""
        docs = [_FakeDoc(False), _FakeDoc(None)]
        view = self._view(docs)
        self._run(view, True)
        self.assertEqual([doc.enabled for doc in docs], [True, True])

    def test_a_write_bumps_changes_and_drops_caches_once(self):
        """One bulk action, one change and one cache drop."""
        view = self._view([_FakeDoc(True), _FakeDoc(True)])
        add_changes, _flash = self._run(view, False)
        add_changes.assert_called_once_with()
        self.assertEqual(view.bulk_calls, 1)

    def test_nothing_to_do_leaves_changes_and_caches_alone(self):
        """A selection that is already in the wanted state writes nothing."""
        view = self._view([_FakeDoc(False)])
        add_changes, flash = self._run(view, False)
        add_changes.assert_not_called()
        self.assertEqual(view.bulk_calls, 0)
        flash.assert_called_once()

    def test_hidden_where_the_model_has_no_enabled_field(self):
        """Nothing to switch, nothing to offer."""
        view = self._view([], fields=('name',))
        for name in ('enable', 'disable'):
            self.assertFalse(
                self.default_module.DefaultModelView.is_action_allowed(view, name))

    def test_offered_where_the_model_can_be_switched(self):
        """Every model with an enabled field gets both actions."""
        view = self._view([])
        for name in ('enable', 'disable'):
            self.assertTrue(
                self.default_module.DefaultModelView.is_action_allowed(view, name))
