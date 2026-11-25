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
                patch.object(views, 'url_for', lambda _endpoint, **args: '/?' + urlencode(args)), \
                patch.object(views, 'flash') as flash:
            # Past Flask-Admin's access check, which needs a login: the
            # right to save into an account is checked by the endpoint
            response = View.save_account.__wrapped__(view)
        return response, written, flash

    def test_the_settings_of_the_form_are_written(self):
        response, written, _ = self._save(
            {'account': 'snow', 'table': 'cmdb_ci', 'api_path': '/api/now',
             'hostname_field': 'fqdn', 'sysparm_query': ' a=1^b=2 ',
             'sysparm_fields': 'name,fqdn'},
            existing=('tables', 'api_path', 'hostname_field', 'sysparm_query',
                      'sysparm_fields'))
        self.assertEqual(written, {'tables': 'cmdb_ci', 'api_path': '/api/now',
                                   'hostname_field': 'fqdn', 'sysparm_query': 'a=1^b=2',
                                   'sysparm_fields': 'name,fqdn'})
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

    def test_a_class_without_records_shows_none(self):
        context, _ = self._page({'account': 'snow', 'table': 'cmdb_ci', 'class_id': 'x'}, [])
        self.assertEqual(context['entry']['names'], [])
