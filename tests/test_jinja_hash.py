"""
The `hash` Jinja filter.

Attributes whose value cannot be a Checkmk label — a comma-separated
list, a value with spaces, a service pattern — become usable as a rule
condition by hashing them: the value stays unreadable but identical for
identical input, so the hosts sharing it share the label.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import types
import unittest


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


class JinjaHashTest(unittest.TestCase):

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

    def render(self, template, **context):
        return self.module.render_jinja(template, **context)

    def test_the_filter_is_available_in_templates(self):
        self.assertEqual(len(self.render("{{ v | hash }}", v='x')), 8)

    def test_the_same_value_always_gives_the_same_hash(self):
        first = self.render("{{ v | hash }}", v='web, db, cache')
        second = self.render("{{ v | hash }}", v='web, db, cache')
        self.assertEqual(first, second)
        # Not Python's hash(): that one is salted per process and would
        # produce a different label on every run.
        self.assertEqual(first, self.module.syncer_hash('web, db, cache'))

    def test_different_values_give_different_hashes(self):
        self.assertNotEqual(self.render("{{ v | hash }}", v='a'),
                            self.render("{{ v | hash }}", v='b'))

    def test_the_result_is_usable_as_a_label_value(self):
        for value in ('web, db, cache', 'Data Center 1', 'Interface *',
                      '^CPU load$'):
            rendered = self.render("{{ v | hash }}", v=value)
            self.assertTrue(rendered.isalnum(), rendered)
            self.assertEqual(rendered, rendered.strip())

    def test_the_length_can_be_chosen(self):
        self.assertEqual(len(self.render("{{ v | hash(16) }}", v='x')), 16)
        # Clamped: too short collides, longer than the digest is pointless.
        self.assertEqual(len(self.module.syncer_hash('x', length=1)), 4)
        self.assertEqual(len(self.module.syncer_hash('x', length=999)), 64)
        self.assertEqual(len(self.module.syncer_hash('x', length='nonsense')), 8)

    def test_a_list_hashes_regardless_of_its_order(self):
        # For grouping hosts the order of a list carries no meaning, and
        # a set has none at all.
        self.assertEqual(self.module.syncer_hash(['web', 'db']),
                         self.module.syncer_hash(['db', 'web']))
        self.assertEqual(self.module.syncer_hash({'web', 'db'}),
                         self.module.syncer_hash(['db', 'web']))

    def test_surrounding_whitespace_does_not_change_the_hash(self):
        self.assertEqual(self.module.syncer_hash('  prod  '),
                         self.module.syncer_hash('prod'))

    def test_none_and_empty_are_the_same(self):
        self.assertEqual(self.module.syncer_hash(None),
                         self.module.syncer_hash(''))

    def test_it_also_works_as_a_function(self):
        self.assertEqual(self.render("{{ hash_value(v) }}", v='x'),
                         self.module.syncer_hash('x'))

    def test_it_works_in_strict_mode(self):
        self.assertEqual(
            self.module.render_jinja("{{ v | hash }}", mode='raise', v='x'),
            self.module.syncer_hash('x'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
