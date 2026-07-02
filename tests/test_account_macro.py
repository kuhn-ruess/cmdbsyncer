"""
Regression tests for the {{ACCOUNT:...}} macro handling in render_jinja.

Two fixes are covered:
  - An ACCOUNT macro whose account cannot be resolved used to survive
    substitution and reach Jinja with its literal colons, raising an
    uncaught TemplateSyntaxError (500 on the host debug page / inventory
    export). It must now nullify to "" instead.
  - The macro is matched with surrounding whitespace, so the natural
    Jinja spelling `{{ ACCOUNT:name:field }}` resolves like the compact
    `{{ACCOUNT:name:field}}`.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import types
import unittest


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


class AccountMacroRenderTest(unittest.TestCase):
    """render_jinja must resolve/whitespace-tolerate the ACCOUNT macro and
    never crash on an unresolvable one."""

    @classmethod
    def setUpClass(cls):
        # tests/__init__.py stubs render_jinja with a MagicMock; load the
        # real implementation for these tests and keep the stub to restore.
        # syncer_jinja imports get_account_variable at module load, so the
        # get_account stub must expose it before we import the real module.
        get_acc = sys.modules['application.helpers.get_account']
        if not hasattr(get_acc, 'get_account_variable'):
            get_acc.get_account_variable = lambda macro: None
        cls._stub = sys.modules.get('application.helpers.syncer_jinja')
        cls.module = _load_source(
            'application.helpers.syncer_jinja',
            os.path.join('application', 'helpers', 'syncer_jinja.py'),
        )

    @classmethod
    def tearDownClass(cls):
        if cls._stub is not None:
            sys.modules['application.helpers.syncer_jinja'] = cls._stub

    def setUp(self):
        # Route the macro replacement through a controllable fake account
        # store instead of the real Mongo-backed one.
        self._orig = self.module.get_account_variable

        def fake(macro):
            inner = macro.strip().removeprefix('{{').removesuffix('}}')
            _, account, var = (p.strip() for p in inner.split(':'))
            if account != 'known':
                raise ValueError("Account Variable not found")
            return f'secret-{var}'

        self.module.get_account_variable = fake

    def tearDown(self):
        self.module.get_account_variable = self._orig

    def test_unresolvable_account_nullifies_instead_of_crashing(self):
        # The account does not exist, so the macro survives substitution
        # and would otherwise blow up Jinja with a TemplateSyntaxError.
        self.assertEqual(
            self.module.render_jinja('{{ACCOUNT:missing:password}}', mode='nullify'),
            '',
        )

    def test_unresolvable_account_ignore_mode_does_not_crash(self):
        self.assertEqual(
            self.module.render_jinja('{{ACCOUNT:missing:password}}', mode='ignore'),
            '',
        )

    def test_compact_macro_resolves(self):
        self.assertEqual(
            self.module.render_jinja('{{ACCOUNT:known:password}}'),
            'secret-password',
        )

    def test_spaced_macro_resolves(self):
        self.assertEqual(
            self.module.render_jinja('{{ ACCOUNT:known:password }}'),
            'secret-password',
        )
