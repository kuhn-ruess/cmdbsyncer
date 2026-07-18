"""
Regression tests for reported security issues.

Each test pins one concrete attack path, so a later refactor that
reintroduces it fails here instead of in production.

tests/__init__.py stubs most of the application package, so the modules
under test are loaded from source the same way test_account_macro does.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import ast
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_source(module_name, relative_path):
    """Load a source file as `module_name`, ensuring its parent package exists."""
    parent = module_name.rsplit('.', 1)[0]
    if parent and parent not in sys.modules:
        sys.modules[parent] = types.ModuleType(parent)
        sys.modules[parent].__path__ = []  # mark as package
    path = os.path.join(_REPO_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _stub_missing_dependencies():
    """The stubbed mongoengine/views packages lack what our modules import."""
    mongoengine = sys.modules.get('mongoengine')
    if mongoengine is not None and not hasattr(mongoengine, 'signals'):
        signals = types.ModuleType('mongoengine.signals')
        signals.post_save = MagicMock()
        signals.post_delete = MagicMock()
        mongoengine.signals = signals
        sys.modules['mongoengine.signals'] = signals


_stub_missing_dependencies()

get_account = _load_source(
    'application.helpers.get_account', 'application/helpers/get_account.py')


class AccountSecretMaskingTest(unittest.TestCase):
    """
    {{ACCOUNT:<name>:password}} must keep resolving during a sync, but be
    masked wherever a rule outcome is rendered back to a browser — the
    host debug page is reachable with a plugin role alone.
    """

    ACCOUNT = {'password': 'sup3rs3cret', 'address': 'https://cmk.example'}

    def _resolve(self, macro):
        with patch.object(get_account, 'get_account_by_name',
                          return_value=self.ACCOUNT):
            return get_account.get_account_variable(macro)

    def test_secret_resolves_outside_the_masking_context(self):
        self.assertEqual(self._resolve('{{ACCOUNT:mon:password}}'), 'sup3rs3cret')

    def test_secret_is_masked_inside_the_masking_context(self):
        with get_account.mask_account_secrets():
            value = self._resolve('{{ACCOUNT:mon:password}}')
        self.assertEqual(value, get_account.SECRET_PLACEHOLDER)

    def test_non_secret_fields_stay_readable_while_masking(self):
        with get_account.mask_account_secrets():
            value = self._resolve('{{ACCOUNT:mon:address}}')
        self.assertEqual(value, 'https://cmk.example')

    def test_masking_is_reset_after_the_block(self):
        with get_account.mask_account_secrets():
            pass
        self.assertEqual(self._resolve('{{ACCOUNT:mon:password}}'), 'sup3rs3cret')


class RuleRoleTest(unittest.TestCase):
    """
    The generic rule views check has_right('rule'); the role has to exist
    in the choices list, otherwise it can never be granted and the views
    are global-admin-only by accident.

    application/models/user.py cannot be imported under the test stubs
    (metaclass conflict on the Document base), so the roles list is read
    from the source with ast.
    """

    def test_rule_role_is_grantable(self):
        path = os.path.join(_REPO_ROOT, 'application', 'models', 'user.py')
        with open(path, encoding='utf-8') as source_file:
            tree = ast.parse(source_file.read())
        idents = []
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(getattr(t, 'id', None) == 'roles' for t in node.targets):
                continue
            for element in node.value.elts:
                idents.append(element.elts[0].value)
        self.assertIn('rule', idents)

    def test_rule_views_check_that_role(self):
        path = os.path.join(_REPO_ROOT, 'application', 'modules', 'rule', 'views.py')
        with open(path, encoding='utf-8') as source_file:
            self.assertIn("has_right('rule')", source_file.read())
