"""A cron group whose account reference is dangling has to stay usable.

Importing ``cron_groups`` without the matching ``accounts`` (rule
import) leaves the jobs pointing at an account id that no Account row
matches. Dereferencing such a reference raises ``DoesNotExist``, which
used to turn the cron group list and its edit form into a 500 — the
very two pages an operator needs to correct the reference.
"""
# pylint: disable=missing-class-docstring,missing-function-docstring
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from mongoengine.errors import DoesNotExist

# tests/__init__.py stubs `application` but not these attributes; the
# cron model and view sources need them at import time.
sys.modules['application'].cron_register = MagicMock(name='stub.cron_register')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stub_module(name, **attrs):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load(name, relative_path):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, relative_path),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_stub_module('application.helpers.sates', add_changes=lambda num=1: None)
_stub_module('application.models.user', is_readonly=lambda user: False)
_stub_module('application._version', __version__='1.2.3')

_cron_model = _load('application.models.cron', 'application/models/cron.py')
_cron_view = _load('application.views.cron', 'application/views/cron.py')


class _StubAccount:  # pylint: disable=too-few-public-methods
    def __init__(self, name):
        self.name = name
        self.id = '651a4c0f9f1b2a0001d0aaaa'

    def __str__(self):
        return f"{self.name} (cmk)"


class _StubEntry:
    """Stand-in for a `GroupEntry`: reading `.account` dereferences and
    raises when the row is gone, `to_mongo()` hands out the raw id."""

    def __init__(self, name, account=None, account_id=None):
        self.name = name
        self.command = 'cmk-export_hosts'
        self._account = account
        self.account_id = account_id or getattr(account, 'id', None)

    @property
    def account(self):
        if self.account_id and self._account is None:
            raise DoesNotExist(
                f"Trying to dereference unknown document {self.account_id}")
        return self._account

    @account.setter
    def account(self, value):
        self._account = value
        self.account_id = getattr(value, 'id', None)

    def to_mongo(self):
        return {'account': self.account_id} if self.account_id else {}

    def __getitem__(self, key):
        return getattr(self, key)


class _StubGroup:  # pylint: disable=too-few-public-methods
    def __init__(self, jobs):
        self.jobs = jobs


class JobAccountHelperTest(unittest.TestCase):

    def test_dangling_reference_reads_as_none(self):
        entry = _StubEntry('export', account_id='651a4c0f9f1b2a0001d0bbbb')
        self.assertIsNone(_cron_model.job_account(entry))

    def test_existing_reference_is_returned(self):
        account = _StubAccount('prod')
        self.assertIs(_cron_model.job_account(_StubEntry('export', account)),
                      account)

    def test_account_id_is_read_without_dereferencing(self):
        entry = _StubEntry('export', account_id='651a4c0f9f1b2a0001d0bbbb')
        self.assertEqual(_cron_model.job_account_id(entry),
                         '651a4c0f9f1b2a0001d0bbbb')

    def test_job_without_account_has_no_id(self):
        self.assertEqual(_cron_model.job_account_id(_StubEntry('export')), '')


class RenderCronjobTest(unittest.TestCase):

    def _render(self, jobs):
        return _cron_view._render_cronjob(  # pylint: disable=protected-access
            None, None, _StubGroup(jobs), 'render_jobs')

    def test_missing_account_is_named_instead_of_raising(self):
        markup = self._render(
            [_StubEntry('export', account_id='651a4c0f9f1b2a0001d0bbbb')])
        self.assertIn('account missing', markup)

    def test_existing_account_is_still_rendered(self):
        markup = self._render([_StubEntry('export', _StubAccount('prod'))])
        self.assertIn('prod (cmk)', markup)
        self.assertNotIn('account missing', markup)

    def test_job_without_account_stays_empty(self):
        markup = self._render([_StubEntry('export')])
        self.assertNotIn('account missing', markup)


class CronGroupGetOneTest(unittest.TestCase):
    """The edit form has to open so the reference can be corrected."""

    def _get_one(self, group):
        view = _cron_view.CronGroupView.__new__(_cron_view.CronGroupView)
        parent = _cron_view.DefaultModelView
        flashes = []
        with patch.object(parent, 'get_one',
                          lambda _self, _id: group, create=True), \
             patch.object(_cron_view, 'flash',
                          lambda message, category: flashes.append(message)), \
             patch.object(_cron_view, 'request',
                          types.SimpleNamespace(method='GET')):
            return view.get_one('any-id'), flashes

    def test_dangling_reference_is_cleared_and_flagged(self):
        entry = _StubEntry('export', account_id='651a4c0f9f1b2a0001d0bbbb')
        model, flashes = self._get_one(_StubGroup([entry]))
        self.assertIsNone(model.jobs[0].account)
        self.assertEqual(len(flashes), 1)
        self.assertIn('export', flashes[0])

    def test_intact_group_is_left_alone(self):
        account = _StubAccount('prod')
        model, flashes = self._get_one(_StubGroup([_StubEntry('export',
                                                              account)]))
        self.assertIs(model.jobs[0].account, account)
        self.assertEqual(flashes, [])


if __name__ == '__main__':
    unittest.main()
