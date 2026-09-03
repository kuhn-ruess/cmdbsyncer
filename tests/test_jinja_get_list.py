"""
The `get_list` Jinja helper.

Rules name attributes that not every host carries. Jinja hands such a
variable in as an undefined value, and handing it back unchanged made
the next operation on it fail — one host missing one attribute took the
whole rule down. A list of nothing is an empty list.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import types
import unittest

import jinja2


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_source(module_name, relative_path):
    """Load a source file as `module_name`, ensuring its parent exists."""
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


class JinjaGetListTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
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

    def get_list(self, value):
        return self.module.get_list(value)

    def render(self, template, **context):
        return self.module.render_jinja(template, **context)

    def test_a_literal_is_its_own_result(self):
        # Values without Jinja skip the compile/render pipeline. Whatever
        # they return has to stay what Jinja returned for them.
        for value in ('plain literal', '  padded  ', "{'a': 1, 'b': (2, 3)}",
                      '100%', 'a{b}c', '}}', '%}', '', 'with\nnewline'):
            self.assertEqual(self.render(value), str(value).replace(
                '\n', '').strip())
        self.assertFalse(self.module.is_template('no jinja here'))
        self.assertFalse(self.module.is_template("{'a': 1}"))
        for template in ('{{ x }}', '{% if x %}y{% endif %}', '{# c #}'):
            self.assertTrue(self.module.is_template(template))

    def test_an_undefined_variable_is_an_empty_list(self):
        self.assertEqual(self.get_list(jinja2.Undefined(name='x')), [])
        self.assertEqual(self.get_list(jinja2.StrictUndefined(name='x')), [])
        self.assertEqual(self.get_list(None), [])

    def test_a_missing_attribute_does_not_break_the_template(self):
        # Two attributes looped over together, only one of them set.
        template = ("{% for entry in get_list(a) + get_list(b) %}"
                    "{{ entry }},{% endfor %}")
        self.assertEqual(self.render(template, a='x, y'), 'x,y,')
        self.assertEqual(self.render(template), '')

    def test_a_single_entry_is_still_a_list(self):
        # A {% for %} loop that writes quoted entries produces '"web",'
        # for a one element list. That parses as the bare string 'web',
        # and the caller looping over the result got its letters.
        self.assertEqual(self.get_list('"web",'), ['web'])
        self.assertEqual(self.get_list("'web'"), ['web'])
        template = ('{% for entry in get_list(services) %}'
                    '"{{ entry }}",{% endfor %}')
        self.assertEqual(
            self.get_list(self.render(template, services="['web']")), ['web'])
        self.assertEqual(
            self.get_list(self.render(template, services="['web','db']")),
            ['web', 'db'])

    def test_a_literal_that_is_no_list_is_wrapped(self):
        # Anything else that parses to a single object is one entry, not
        # something to iterate over: a number has no letters to hand out,
        # it made the caller fail outright.
        self.assertEqual(self.get_list('5'), [5])
        self.assertEqual(self.get_list('True'), [True])
        self.assertEqual(self.get_list("{'a': 1}"), [{'a': 1}])

    def test_the_known_shapes_still_work(self):
        self.assertEqual(self.get_list(['a', 'b']), ['a', 'b'])
        self.assertEqual(self.get_list(('a', 'b')), ['a', 'b'])
        self.assertEqual(self.get_list("['a', 'b']"), ['a', 'b'])
        self.assertEqual(self.get_list('a, b'), ['a', 'b'])
        self.assertEqual(self.get_list('a, b,'), ['a', 'b'])
        self.assertEqual(self.get_list('1, 2'), [1, 2])
        self.assertEqual(self.get_list(''), [])
