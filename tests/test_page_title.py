"""Browser tab title of the admin pages: most specific part first."""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import unittest
from types import SimpleNamespace

from flask import Flask

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Loaded directly: tests/__init__ stubs the `application.helpers` package.
_spec = importlib.util.spec_from_file_location(
    'page_title_under_test',
    os.path.join(REPO_ROOT, 'application', 'helpers', 'page_title.py'),
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
page_title = _module.page_title


def _category(name, parent=None):
    return SimpleNamespace(name=name, parent=parent)


def _view(name, category=None, categories=()):
    menu = {item.name: item for item in categories}
    admin = SimpleNamespace(get_category_menu_item=menu.get)
    return SimpleNamespace(name=name, category=category, admin=admin)


class PageTitleTest(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['HEADER_HINT'] = ''
        # Register the endpoints the tests request.
        for rule, endpoint in (('/host/', 'host.index_view'),
                               ('/host/edit/', 'host.edit_view'),
                               ('/host/set_template_form', 'host.set_template_form'),
                               ('/rule/', 'rule.index_view')):
            self.app.add_url_rule(rule, endpoint, lambda: '')
        objects = _category('Objects')
        modules = _category('Modules')
        ansible = _category('Ansible', modules)
        self.categories = (objects, modules, ansible, _category('Rules', ansible))
        self.hosts = _view('Hosts', 'Objects', self.categories)

    def _title(self, url, view, obj=None):
        with self.app.test_request_context(url):
            return page_title(view, obj)

    def test_list_names_view_and_menu(self):
        self.assertEqual(self._title('/host/', self.hosts),
                         'Hosts · Objects – cmdbsyncer')

    def test_edit_names_the_document_first(self):
        host = SimpleNamespace(hostname='web01')
        self.assertEqual(self._title('/host/edit/', self.hosts, host),
                         'Edit web01 · Hosts · Objects – cmdbsyncer')

    def test_own_page_is_named_after_its_endpoint(self):
        self.assertEqual(self._title('/host/set_template_form', self.hosts),
                         'Set Template · Hosts · Objects – cmdbsyncer')

    def test_top_level_menu_is_dropped_below_a_sub_menu(self):
        view = _view('Filter', 'Rules', self.categories)
        self.assertEqual(self._title('/rule/', view),
                         'Filter · Rules · Ansible – cmdbsyncer')

    def test_header_hint_tells_installations_apart(self):
        self.app.config['HEADER_HINT'] = 'TEST'
        self.assertEqual(self._title('/host/', self.hosts),
                         'Hosts · Objects – cmdbsyncer TEST')


if __name__ == '__main__':
    unittest.main()
