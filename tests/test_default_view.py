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


class _BaseModelView:  # pylint: disable=too-few-public-methods
    """Minimal parent class used to observe super() calls."""

    def on_model_change(self, form, model, is_created):
        """Return the call arguments so tests can assert on them."""
        return {"form": form, "model": model, "created": is_created}


class _EndpointLinkRowAction:  # pylint: disable=too-few-public-methods
    """Simple placeholder matching Flask-Admin's constructor shape."""

    def __init__(self, *_args, **_kwargs):
        pass


class DefaultViewModelChangeTest(unittest.TestCase):
    """Verify DefaultModelView model normalization behavior."""

    @classmethod
    def setUpClass(cls):
        """Load the real module under lightweight import stubs."""
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
            "flask_admin",
            AdminIndexView=object,
            expose=lambda *a, **k: (lambda fn: fn),
        )
        _stub_module(
            "flask_admin.contrib.mongoengine",
            ModelView=_BaseModelView,
        )
        _stub_module(
            "flask_admin.model.template",
            EndpointLinkRowAction=_EndpointLinkRowAction,
        )
        _stub_module("flask_admin.helpers", get_redirect_target=lambda: "")
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
        cls.default_module = module

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
