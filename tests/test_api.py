"""
Integration tests for the Flask-RESTX API endpoints.

Covers:
  - application.api.require_token (auth, roles, HTTPS gating)
  - application.api.syncer (logs, services, cron, hosts)
  - application.api.objects (host CRUD, bulk, inventory, listing)

The test stubs in tests/__init__.py replace MongoEngine models with
MagicMock-based doubles, so no live database is required. A minimal Flask
app is built per-test-class and the real API namespaces are mounted on it.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import base64
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from flask import Blueprint, Flask
from flask_restx import Api
from mongoengine.errors import DoesNotExist

from application.api.objects import API as OBJECTS_API
from application.api.syncer import API as SYNCER_API
from application.helpers.get_account import AccountNotFoundError


def _build_app():
    """Build a Flask app with both API namespaces mounted under /api/v1."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret'
    app.config['ALLOW_INSECURE_API_AUTH'] = True
    blueprint = Blueprint('api', __name__)
    api = Api(blueprint, doc=False)
    api.add_namespace(SYNCER_API, path='/syncer')
    api.add_namespace(OBJECTS_API, path='/objects')
    app.register_blueprint(blueprint, url_prefix='/api/v1')
    return app


def _basic_auth(username='tester', password='secret'):
    raw = f"{username}:{password}".encode()
    return {'Authorization': 'Basic ' + base64.b64encode(raw).decode()}


class _FakeUser:  # pylint: disable=too-few-public-methods
    """Minimal stand-in for application.models.user.User instances."""

    def __init__(self, api_roles=None, password_ok=True, disabled=False):
        self.api_roles = api_roles if api_roles is not None else ['all']
        self.disabled = disabled
        self._password_ok = password_ok

    def check_password(self, _password):
        return self._password_ok


class APIAuthTest(unittest.TestCase):
    """Auth behavior of the require_token decorator."""

    def setUp(self):
        self.app = _build_app()
        self.client = self.app.test_client()

    def test_no_credentials_returns_401(self):
        resp = self.client.get('/api/v1/syncer/hosts')
        self.assertEqual(resp.status_code, 401)

    def test_malformed_login_header_returns_401(self):
        resp = self.client.get(
            '/api/v1/syncer/hosts',
            headers={'x-login-user': 'no-colon'},
        )
        self.assertEqual(resp.status_code, 401)

    @patch('application.api.User')
    def test_unknown_user_returns_401(self, user_cls):
        user_cls.objects.get.side_effect = DoesNotExist
        resp = self.client.get('/api/v1/syncer/hosts', headers=_basic_auth())
        self.assertEqual(resp.status_code, 401)

    @patch('application.api.syncer.Host')
    @patch('application.api.User')
    def test_valid_basic_auth_passes(self, user_cls, host_cls):
        user_cls.objects.get.return_value = _FakeUser(api_roles=['all'])
        host_cls.objects.return_value.count.return_value = 0
        resp = self.client.get('/api/v1/syncer/hosts', headers=_basic_auth())
        self.assertEqual(resp.status_code, 200)

    @patch('application.api.syncer.Host')
    @patch('application.api.User')
    def test_x_login_user_header_passes(self, user_cls, host_cls):
        user_cls.objects.get.return_value = _FakeUser(api_roles=['all'])
        host_cls.objects.return_value.count.return_value = 0
        resp = self.client.get(
            '/api/v1/syncer/hosts',
            headers={'x-login-user': 'tester:secret'},
        )
        self.assertEqual(resp.status_code, 200)

    @patch('application.api.User')
    def test_wrong_password_returns_401(self, user_cls):
        user_cls.objects.get.return_value = _FakeUser(password_ok=False)
        resp = self.client.get('/api/v1/syncer/hosts', headers=_basic_auth())
        self.assertEqual(resp.status_code, 401)

    @patch('application.api.User')
    def test_role_restriction_blocks_other_namespace(self, user_cls):
        # A user with only 'syncer' role must not reach /objects/*.
        user_cls.objects.get.return_value = _FakeUser(api_roles=['syncer'])
        resp = self.client.get('/api/v1/objects/some-host', headers=_basic_auth())
        self.assertEqual(resp.status_code, 401)

    @patch('application.api.syncer.Host')
    @patch('application.api.User')
    def test_role_matching_path_prefix_allowed(self, user_cls, host_cls):
        user_cls.objects.get.return_value = _FakeUser(api_roles=['syncer'])
        host_cls.objects.return_value.count.return_value = 0
        resp = self.client.get('/api/v1/syncer/hosts', headers=_basic_auth())
        self.assertEqual(resp.status_code, 200)

    @patch('application.api.User')
    def test_https_required_when_insecure_flag_off(self, user_cls):
        user_cls.objects.get.return_value = _FakeUser()
        # Drop the flag and force a non-loopback, non-localhost request.
        self.app.config['ALLOW_INSECURE_API_AUTH'] = False
        resp = self.client.get(
            '/api/v1/syncer/hosts',
            headers={**_basic_auth(), 'Host': 'cmdb.example.com'},
            environ_overrides={'REMOTE_ADDR': '10.0.0.5'},
        )
        self.assertEqual(resp.status_code, 401)


def _auth_patches(test_fn):
    """Decorator: inject a valid user so auth always passes."""
    @patch('application.api.User')
    def wrapper(self, user_cls, *args, **kwargs):
        user_cls.objects.get.return_value = _FakeUser(api_roles=['all'])
        return test_fn(self, *args, **kwargs)
    wrapper.__name__ = test_fn.__name__
    return wrapper


class SyncerAPITest(unittest.TestCase):
    """Tests for /api/v1/syncer/*"""

    def setUp(self):
        self.app = _build_app()
        self.client = self.app.test_client()
        self.headers = _basic_auth()

    @_auth_patches
    @patch('application.api.syncer.LogEntry')
    def test_logs_returns_entries(self, log_cls):
        detail = MagicMock(level='info', message='hi')
        entry = MagicMock()
        entry.id = 'abc123'
        entry.datetime = datetime(2026, 1, 2, 3, 4, 5)
        entry.message = 'a message'
        entry.source = 'testsrc'
        entry.details = [detail]
        entry.traceback = '  trace  '
        entry.has_error = False
        # Support LogEntry.objects().order_by('-id')[:limit]
        chain = MagicMock()
        chain.order_by.return_value = [entry]
        log_cls.objects.return_value = chain

        resp = self.client.get('/api/v1/syncer/logs', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body['result']), 1)
        item = body['result'][0]
        self.assertEqual(item['entry_id'], 'abc123')
        self.assertEqual(item['source'], 'testsrc')
        self.assertEqual(item['details'], [{'name': 'info', 'message': 'hi'}])
        self.assertEqual(item['traceback'], 'trace')
        self.assertFalse(item['has_error'])

    @_auth_patches
    @patch('application.api.syncer.LogEntry')
    def test_service_lookup_returns_entry(self, log_cls):
        detail = MagicMock(level='err', message='boom')
        entry = MagicMock()
        entry.id = 'xyz'
        entry.datetime = datetime(2026, 1, 1, 0, 0, 0)
        entry.message = 'oops'
        entry.source = 'svc'
        entry.details = [detail]
        entry.traceback = ''
        entry.has_error = True
        chain = MagicMock()
        chain.order_by.return_value.first.return_value = entry
        log_cls.objects.return_value = chain

        resp = self.client.get('/api/v1/syncer/services/svc', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['result']['entry_id'], 'xyz')
        self.assertTrue(body['result']['has_error'])
        log_cls.objects.assert_called_once_with(source='svc')

    @_auth_patches
    @patch('application.api.syncer.LogEntry')
    def test_service_lookup_404_when_missing(self, log_cls):
        chain = MagicMock()
        chain.order_by.return_value.first.return_value = None
        log_cls.objects.return_value = chain

        resp = self.client.get('/api/v1/syncer/services/unknown', headers=self.headers)

        self.assertEqual(resp.status_code, 404)
        self.assertIn('error', resp.get_json())

    @_auth_patches
    @patch('application.api.syncer.CronStats')
    def test_cron_get_returns_statuses(self, cron_cls):
        stat = MagicMock()
        stat.group = 'nightly'
        stat.last_start = datetime(2026, 1, 1, 2, 0, 0)
        stat.next_run = datetime(2026, 1, 2, 2, 0, 0)
        stat.is_running = False
        stat.last_message = 'ok'
        stat.failure = False
        cron_cls.objects = [stat]

        resp = self.client.get('/api/v1/syncer/cron/', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['result'][0]['name'], 'nightly')
        self.assertEqual(body['result'][0]['last_start'], '2026-01-01 02:00:00')
        self.assertFalse(body['result'][0]['has_error'])

    @_auth_patches
    @patch('application.api.syncer.CronGroup')
    def test_cron_post_updates_run_once_next(self, group_cls):
        group = MagicMock()
        group_cls.objects.get.return_value = group

        resp = self.client.post(
            '/api/v1/syncer/cron/',
            headers=self.headers,
            json={'job_name': 'nightly', 'run_once_next': True},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'saved'})
        group_cls.objects.get.assert_called_once_with(name='nightly')
        self.assertTrue(group.run_once_next)
        group.save.assert_called_once()

    @_auth_patches
    @patch('application.api.syncer.CronGroup')
    def test_cron_post_404_when_job_missing(self, group_cls):
        group_cls.objects.get.side_effect = DoesNotExist

        resp = self.client.post(
            '/api/v1/syncer/cron/',
            headers=self.headers,
            json={'job_name': 'missing', 'run_once_next': False},
        )

        self.assertEqual(resp.status_code, 404)

    @_auth_patches
    def test_cron_post_payload_validation(self):
        # Missing required `run_once_next` triggers Flask-RESTX validation.
        resp = self.client.post(
            '/api/v1/syncer/cron/',
            headers=self.headers,
            json={'job_name': 'nightly'},
        )
        self.assertEqual(resp.status_code, 400)

    @_auth_patches
    @patch('application.api.syncer.Host')
    def test_hosts_counts(self, host_cls):
        # Host.objects(is_object=False).count() / is_object=True / age filter
        def objects_side_effect(**kwargs):
            mock = MagicMock()
            if kwargs.get('is_object') is False and 'last_import_seen__lt' in kwargs:
                mock.count.return_value = 2
            elif kwargs.get('is_object') is False:
                mock.count.return_value = 7
            elif kwargs.get('is_object') is True:
                mock.count.return_value = 3
            else:
                mock.count.return_value = 0
            return mock
        host_cls.objects.side_effect = objects_side_effect

        resp = self.client.get('/api/v1/syncer/hosts', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['num_hosts'], 7)
        self.assertEqual(body['num_objects'], 3)
        self.assertEqual(body['not_updated_last_24h'], 2)
        self.assertIn('24h_checkpoint', body)


class ObjectsAPITest(unittest.TestCase):
    """Tests for /api/v1/objects/*"""

    def setUp(self):
        self.app = _build_app()
        self.client = self.app.test_client()
        self.headers = _basic_auth()

    def _make_host(self, hostname='web01', labels=None, inventory=None):
        host = MagicMock()
        host.hostname = hostname
        host.get_labels.return_value = labels or {'env': 'prod'}
        host.get_inventory.return_value = inventory or {'cpu': 4}
        host.last_import_seen = datetime(2026, 1, 1, 0, 0, 0)
        host.last_import_sync = datetime(2026, 1, 2, 0, 0, 0)
        return host

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_get_host_returns_attributes(self, host_cls):
        host_cls.objects.get.return_value = self._make_host()

        resp = self.client.get('/api/v1/objects/web01', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['hostname'], 'web01')
        self.assertEqual(body['labels'], {'env': 'prod'})
        self.assertEqual(body['inventory'], {'cpu': 4})
        self.assertEqual(body['last_seen'], '2026-01-01T00:00:00Z')
        self.assertEqual(body['last_update'], '2026-01-02T00:00:00Z')

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_get_host_serializes_nested_datetime(self, host_cls):
        host_cls.objects.get.return_value = self._make_host(
            inventory={'last_patch': datetime(2026, 3, 4, 5, 6, 7)},
        )

        resp = self.client.get('/api/v1/objects/web01', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.get_json()['inventory']['last_patch'],
            '2026-03-04T05:06:07Z',
        )

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_get_host_404_when_missing(self, host_cls):
        host_cls.objects.get.side_effect = DoesNotExist

        resp = self.client.get('/api/v1/objects/gone', headers=self.headers)

        self.assertEqual(resp.status_code, 404)

    @_auth_patches
    @patch('application.api.objects.get_account_by_name')
    @patch('application.api.objects.Host')
    def test_post_host_creates_or_updates(self, host_cls, get_account):
        host = MagicMock()
        host.set_account.return_value = False  # no account conflict
        host_cls.get_host.return_value = host
        get_account.return_value = {'name': 'acct', '_id': 'id1'}

        resp = self.client.post(
            '/api/v1/objects/web01',
            headers=self.headers,
            json={'account': 'acct', 'labels': {'env': 'prod'}},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'saved'})
        host_cls.get_host.assert_called_once_with('web01')
        host.update_host.assert_called_once_with({'env': 'prod'})
        host.set_account.assert_called_once()

    @_auth_patches
    @patch('application.api.objects.get_account_by_name')
    def test_post_host_400_when_account_missing(self, get_account):
        get_account.side_effect = AccountNotFoundError("nope")

        resp = self.client.post(
            '/api/v1/objects/web01',
            headers=self.headers,
            json={'account': 'missing', 'labels': {}},
        )

        self.assertEqual(resp.status_code, 400)

    @_auth_patches
    def test_post_host_validation_rejects_missing_fields(self):
        resp = self.client.post(
            '/api/v1/objects/web01',
            headers=self.headers,
            json={'labels': {}},  # missing `account`
        )
        self.assertEqual(resp.status_code, 400)

    @_auth_patches
    @patch('application.api.objects.CheckmkFolderPool')
    @patch('application.api.objects.Host')
    def test_delete_host_removes_and_decrements_folder(self, host_cls, pool_cls):
        host = MagicMock()
        host.folder = 'web'
        host_cls.get_host.return_value = host
        pool = MagicMock()
        pool.folder_seats_taken = 5
        pool_cls.objects.get.return_value = pool

        resp = self.client.delete('/api/v1/objects/web01', headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'deleted'})
        host.delete.assert_called_once()
        self.assertEqual(pool.folder_seats_taken, 4)
        pool.save.assert_called_once()

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_delete_host_404_when_missing(self, host_cls):
        host_cls.get_host.return_value = None

        resp = self.client.delete('/api/v1/objects/gone', headers=self.headers)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json(), {'status': 'not found'})

    @_auth_patches
    @patch('application.api.objects.get_account_by_name')
    @patch('application.api.objects.Host')
    def test_bulk_post_tracks_saved_and_skipped(self, host_cls, get_account):
        get_account.return_value = {'name': 'acct', '_id': 'id1'}
        saved = MagicMock()
        saved.set_account.return_value = True  # do_save True → counted as saved
        skipped = MagicMock()
        skipped.set_account.return_value = False

        def get_host(name, *_args, **_kwargs):
            return saved if name == 'a' else skipped
        host_cls.get_host.side_effect = get_host

        payload = {
            'account': 'acct',
            'objects': [
                {'hostname': 'a', 'labels': {'env': 'prod'}},
                {'hostname': 'b', 'labels': {'env': 'dev'}},
            ],
        }
        resp = self.client.post(
            '/api/v1/objects/bulk',
            headers=self.headers,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['status'], 'saved 1')
        self.assertEqual(body['not-saved'], ['b'])
        saved.save.assert_called_once()
        skipped.save.assert_not_called()

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_inventory_post_updates_single_host(self, host_cls):
        host = MagicMock()
        host_cls.get_host.return_value = host

        resp = self.client.post(
            '/api/v1/objects/web01/inventory',
            headers=self.headers,
            json={'key': 'facts', 'inventory': {'cpu': 8}},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'saved'})
        host.update_inventory.assert_called_once_with('facts', {'cpu': 8})
        host.save.assert_called_once()

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_inventory_bulk_updates_all(self, host_cls):
        hosts = [MagicMock(), MagicMock()]
        host_cls.get_host.side_effect = hosts

        payload = {
            'inventories': [
                {'hostname': 'a', 'key': 'facts', 'inventory': {'cpu': 1}},
                {'hostname': 'b', 'key': 'facts', 'inventory': {'cpu': 2}},
            ],
        }
        resp = self.client.post(
            '/api/v1/objects/bulk/inventory',
            headers=self.headers,
            json=payload,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'saved 2'})
        for host in hosts:
            host.save.assert_called_once()

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_list_all_paginates(self, host_cls):
        # Build five fake hosts and make Host.objects() sliceable.
        hosts = []
        for idx in range(5):
            hosts.append(MagicMock(
                hostname=f'h{idx}',
                get_labels=MagicMock(return_value={}),
                get_inventory=MagicMock(return_value={}),
                last_import_seen=None,
                last_import_sync=None,
            ))

        class _Queryset:  # pylint: disable=too-few-public-methods
            def __init__(self, items):
                self._items = items

            def count(self):
                return len(self._items)

            def __getitem__(self, item):
                return self._items[item]

        host_cls.objects.return_value = _Queryset(hosts)

        resp = self.client.get(
            '/api/v1/objects/all?start=0&limit=2',
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['size'], 5)
        self.assertEqual(body['start'], 0)
        self.assertEqual(body['limit'], 2)
        self.assertEqual(len(body['results']), 2)
        self.assertIn('next', body['_links'])

    @_auth_patches
    @patch('application.api.objects.Host')
    def test_list_all_final_page_has_no_next_link(self, host_cls):
        hosts = [MagicMock(
            hostname='h0',
            get_labels=MagicMock(return_value={}),
            get_inventory=MagicMock(return_value={}),
            last_import_seen=None,
            last_import_sync=None,
        )]

        class _Queryset:  # pylint: disable=too-few-public-methods
            def __init__(self, items):
                self._items = items

            def count(self):
                return len(self._items)

            def __getitem__(self, item):
                return self._items[item]

        host_cls.objects.return_value = _Queryset(hosts)

        resp = self.client.get(
            '/api/v1/objects/all?start=0&limit=10',
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('next', resp.get_json()['_links'])


if __name__ == '__main__':
    unittest.main()
