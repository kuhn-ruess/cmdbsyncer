"""
Unit tests for the ServiceNow query view: saving the tried settings into the account
"""
# pylint: disable=missing-function-docstring
import importlib.util
import os
import unittest
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import MagicMock, patch

from flask import Flask

_spec = importlib.util.spec_from_file_location(
    'application.plugins.servicenow.views',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'views.py'))
views = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(views)
View = views.ServiceNowQueryView


class TestSaveAccount(unittest.TestCase):
    """Tests for ServiceNowQueryView.save_account"""

    def _save(self, form, may_edit=True, tables='cmdb_ci', existing=()):
        account = MagicMock(name='account')
        account.custom_field.return_value = tables
        accounts = MagicMock(name='accounts')
        accounts.first.return_value = account if tables is not None else None
        written = {}

        def with_field(custom_fields__name):
            found = MagicMock(name=custom_fields__name)

            def update(**change):
                if custom_fields__name not in existing:
                    return 0
                written[custom_fields__name] = change['set__custom_fields__S__value']
                return 1
            found.update.side_effect = update
            return found
        accounts.side_effect = with_field

        def push(push__custom_fields):
            written[push__custom_fields.name] = ('added', push__custom_fields.value)
        accounts.update.side_effect = push
        account_model = MagicMock(name='Account')
        account_model.objects.return_value = accounts
        user = MagicMock(name='user')
        user.has_right.return_value = may_edit
        view = View.__new__(View)
        with Flask(__name__).test_request_context('/', method='POST', data=form), \
                patch.object(views, 'Account', account_model), \
                patch.object(views, 'current_user', user), \
                patch.object(views, 'CustomEntry', SimpleNamespace), \
                patch.object(views, 'url_for',
                             lambda _endpoint, **args: '/?' + urlencode(args, doseq=True)), \
                patch.object(views, 'flash') as flash:
            # Past Flask-Admin's access check, which needs a login: the
            # right to save into an account is checked by the endpoint
            response = View.save_account.__wrapped__(view)
        return response, written, flash

    def test_the_settings_of_the_form_are_written(self):
        response, written, _ = self._save(
            {'account': 'snow', 'table': 'cmdb_ci', 'api_path': '/api/now',
             'hostname_field': 'fqdn', 'sysparm_query': ' a=1^b=2 ',
             'sysparm_fields': 'name,fqdn', 'exclude_accounts': 'csv, ldap'},
            existing=('tables', 'api_path', 'hostname_field', 'sysparm_query',
                      'sysparm_fields', 'compare_exclude_accounts'))
        self.assertEqual(written, {'tables': 'cmdb_ci', 'api_path': '/api/now',
                                   'hostname_field': 'fqdn', 'sysparm_query': 'a=1^b=2',
                                   'sysparm_fields': 'name,fqdn',
                                   'compare_exclude_accounts': 'csv,ldap'})
        self.assertIn('exclude_accounts=csv&exclude_accounts=ldap', response.location)
        self.assertIn('table=cmdb_ci', response.location)

    def test_a_missing_field_is_added(self):
        _, written, _ = self._save({'account': 'snow', 'table': 'cmdb_ci',
                                    'sysparm_query': 'a=1'})
        self.assertEqual(written['sysparm_query'], ('added', 'a=1'))

    def test_all_fields_saves_no_field_list(self):
        _, written, _ = self._save({'account': 'snow', 'sysparm_fields': 'name',
                                    'all_fields': '1'}, existing=('sysparm_fields',))
        self.assertEqual(written['sysparm_fields'], '')

    def test_without_the_account_right_nothing_is_written(self):
        _, written, flash = self._save({'account': 'snow', 'sysparm_query': 'a=1'},
                                       may_edit=False)
        self.assertEqual(written, {})
        self.assertEqual(flash.call_args.args[1], 'danger')

    def test_an_unknown_account_is_refused(self):
        _, written, flash = self._save({'account': 'nope', 'sysparm_query': 'a=1'},
                                       tables=None)
        self.assertEqual(written, {})
        self.assertEqual(flash.call_args.args[1], 'danger')


class TestSavedTables(unittest.TestCase):
    """Tests for saved_tables"""

    def test_a_single_table_is_replaced(self):
        self.assertEqual(views.saved_tables('cmdb_ci_server', 'cmdb_ci'), 'cmdb_ci')

    def test_a_known_table_keeps_the_list(self):
        self.assertEqual(views.saved_tables('a, b', 'b'), 'a,b')

    def test_a_new_table_joins_several(self):
        self.assertEqual(views.saved_tables('a,b', 'c'), 'a,b,c')

    def test_no_table_keeps_the_list(self):
        self.assertEqual(views.saved_tables('a', ''), 'a')

    def test_several_tables_of_the_form_are_the_list(self):
        self.assertEqual(views.saved_tables('a,b', 'c, d'), 'c,d')


if __name__ == '__main__':
    unittest.main()


class TestClassNames(unittest.TestCase):
    """The names of one class on a page of their own"""

    def test_a_class_is_selected_by_its_id(self):
        self.assertEqual(views.class_query('cmdb_ci_linux_server'),
                         'sys_class_name=cmdb_ci_linux_server')

    def test_records_without_class_can_be_selected(self):
        self.assertEqual(views.class_query(''), 'sys_class_nameISEMPTY')

    def _page(self, args, by_class):
        view = View.__new__(View)
        asked = []

        def query(form, _limit, compare=False):
            asked.append((form['sysparm_query'], compare))
            return {'by_class': by_class}
        view._query = query  # pylint: disable=protected-access
        view.render = lambda template, **context: context
        with Flask(__name__).test_request_context('/?' + urlencode(args)):
            return View.class_names.__wrapped__(view), asked

    def test_only_the_class_is_read_with_the_query_of_the_form(self):
        entry = {'class': 'cmdb_ci_linux_server', 'names': [{'name': 'srv01', 'host': True}]}
        context, asked = self._page({'account': 'snow', 'table': 'cmdb_ci',
                                     'sysparm_query': 'operational_status=1',
                                     'class_id': 'cmdb_ci_linux_server'}, [entry])
        self.assertEqual(asked, [('sys_class_name=cmdb_ci_linux_server^operational_status=1',
                                  True)])
        self.assertEqual(context['entry'], entry)

    def test_the_excluded_accounts_travel_with_the_page(self):
        context, _ = self._page([('account', 'snow'), ('table', 'cmdb_ci'), ('class_id', 'x'),
                                 ('exclude_accounts', 'csv'), ('exclude_accounts', 'ldap')], [])
        self.assertEqual(context['form']['exclude_accounts'], ['csv', 'ldap'])

    def test_a_class_without_records_shows_none(self):
        context, _ = self._page({'account': 'snow', 'table': 'cmdb_ci', 'class_id': 'x'}, [])
        self.assertEqual(context['entry']['names'], [])


class TestCompareLeavesAccountsOut(unittest.TestCase):
    """Hosts of excluded accounts are no Syncer hosts in the comparison"""

    def test_the_excluded_accounts_filter_the_export_hosts(self):
        host = MagicMock(name='Host')
        syncer_instance = MagicMock(name='syncer', config={})
        form = {'account': 'snow', 'table': 'cmdb_ci', 'api_path': '', 'hostname_field': '',
                'sysparm_query': '', 'sysparm_fields': '', 'all_fields': False,
                'sysparm_display_value': 'true', 'exclude_accounts': ['csv']}
        with patch.object(views, 'Host', host), \
                patch.object(views, 'SyncServiceNow', return_value=syncer_instance):
            View._query(form, 25, compare=True)  # pylint: disable=protected-access
        host.get_export_hosts.return_value.filter.assert_called_once_with(
            source_account_name__nin=['csv'])


class TestCompareList(unittest.TestCase):
    """One list of a comparison on a page of its own"""

    def _page(self, args):
        view = View.__new__(View)
        view._query = lambda form, _limit, compare=False: {  # pylint: disable=protected-access
            'missing_in_snow': [{'name': 'srv01', 'note': '', 'records': []}]}
        view.render = lambda template, **context: context
        with Flask(__name__).test_request_context('/?' + urlencode(args)):
            return View.compare_list.__wrapped__(view)

    def test_the_list_is_shown_with_the_account_for_its_records(self):
        context = self._page({'list': 'missing_in_snow', 'account': 'snow',
                              'table': 'cmdb_ci', 'sysparm_display_value': 'false',
                              'sysparm_query': 'monitor=true', 'sysparm_fields': 'name,os'})
        self.assertEqual(context['key_fields'], ['sys_class_name', 'name', 'monitor', 'os'])
        self.assertEqual(context['names'][0]['name'], 'srv01')
        self.assertTrue(context['hosts'])
        self.assertFalse(context['classes'])
        self.assertFalse(context['compare_host'])
        self.assertEqual(context['record_args'],
                         {'account': 'snow', 'sysparm_display_value': 'false'})

    def test_an_unknown_list_is_refused(self):
        context = self._page({'list': 'records', 'account': 'snow', 'table': 'cmdb_ci'})
        self.assertIsNone(context['names'])
        self.assertIn('Unknown list', context['error'])


class TestRecord(unittest.TestCase):
    """Every field of one record, for the list page"""

    def _record(self, found, url='/?account=snow&table=cmdb_ci&sys_id=a1', host=None):
        syncer_instance = MagicMock(name='syncer', config={})
        host_model = MagicMock(name='Host')
        host_model.objects.return_value.first.return_value = host
        app = Flask(__name__)
        with app.test_request_context(url), \
                patch.object(views, 'SyncServiceNow', return_value=syncer_instance), \
                patch.object(views, 'Host', host_model), \
                patch.object(views, 'get_record', return_value=found) as get:
            response = View.record.__wrapped__(View.__new__(View))
        return response, get

    def test_the_syncer_host_comes_along_when_asked(self):
        host = MagicMock(name='host', labels={'os': 'linux', 'fqdn': 'srv01'})
        response, _ = self._record({'name': 'srv01'}, '/?account=snow&table=cmdb_ci'
                                   '&sys_id=a1&host=srv01', host)
        self.assertEqual(response.get_json()['host'], [['fqdn', 'srv01'], ['os', 'linux']])
        response, _ = self._record({'name': 'srv01'})
        self.assertNotIn('host', response.get_json())

    def test_the_fields_come_sorted(self):
        response, get = self._record({'name': 'srv01', 'monitor': 'false'})
        self.assertEqual(response.get_json(),
                         {'fields': [['monitor', 'false'], ['name', 'srv01']]})
        self.assertEqual(get.call_args.args[1:], ('cmdb_ci', 'a1'))

    def test_a_missing_record_is_404(self):
        (_, status), _ = self._record(None)
        self.assertEqual(status, 404)


class TestAccountSettings(unittest.TestCase):
    """The settings of an account, read again by the reload button"""

    def test_the_settings_of_the_account(self):
        account = MagicMock(name='account', address='https://snow.example.com')
        account.name = 'snow'
        account.custom_field.side_effect = lambda field, default='': {
            'tables': 'cmdb_ci', 'compare_exclude_accounts': 'csv,ldap'}.get(field, default)
        model = MagicMock(name='Account')
        model.objects.return_value.first.return_value = account
        with Flask(__name__).test_request_context('/?account=snow'), \
                patch.object(views, 'Account', model):
            response = View.account_settings.__wrapped__(View.__new__(View))
        settings = response.get_json()
        self.assertEqual(settings['tables'], ['cmdb_ci'])
        self.assertEqual(settings['exclude_accounts'], ['csv', 'ldap'])
        self.assertEqual(settings['hostname_field'], 'name')


class TestOutsideQuery(unittest.TestCase):
    """A chunk of Syncer hosts looked up without the query"""

    def test_the_names_are_looked_up_with_the_form(self):
        syncer_instance = MagicMock(name='syncer', config={})

        def note(_syncer, tables, entries):
            entries[0]['note'] = f'Outside the query of {tables}'
        with Flask(__name__).test_request_context(
                '/?account=snow&table=cmdb_ci&sysparm_query=monitor%3Dtrue'
                '&name=srv01&name=srv02'), \
                patch.object(views, 'SyncServiceNow', return_value=syncer_instance), \
                patch.object(views, 'note_outside_query', side_effect=note):
            response = View.outside_query.__wrapped__(View.__new__(View))
        self.assertEqual(syncer_instance.config['sysparm_query'], 'monitor=true')
        self.assertEqual(response.get_json()['entries'], [
            {'name': 'srv01', 'note': 'Outside the query of cmdb_ci', 'records': []},
            {'name': 'srv02', 'note': '', 'records': []}])
