"""
i-doit: a category with ten or more entries keeps every entry, and the
description of a rule reaches the object that gets created.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import unittest
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        f'idoit_{name}_under_test',
        os.path.join(REPO_ROOT, 'application', 'plugins', 'idoit', f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_syncer(response=None):
    syncer_class = load_module('syncer').SyncIdoit
    syncer = syncer_class.__new__(syncer_class)
    syncer.config = {'api_token': 't', 'language': 'en',
                     'object_categories': 'C__CATG__IP'}
    syncer.category_cache = {}
    syncer.request = lambda _json: {'result': response}
    return syncer


class CategoryCounterTest(unittest.TestCase):

    @staticmethod
    def read(response):
        syncer = make_syncer(response)
        return next(syncer.get_object_categories(1))['1__C__CATG__IP']

    def test_a_single_entry_has_no_counter(self):
        self.assertEqual(self.read([{'title': 'a'}]), {'ip_title': 'a'})

    def test_entries_past_nine_keep_their_own_key(self):
        data = self.read([{'title': f'v{number}'} for number in range(1, 13)])
        self.assertEqual(data, {f'ip_{number}_title': f'v{number}'
                                for number in range(1, 13)})

    def test_list_values_past_nine_keep_their_own_key(self):
        values = [{'ref': f'v{number}'} for number in range(1, 13)]
        data = self.read([{'hosts': values}])
        self.assertEqual(data, {f'ip_hosts_ref_{number}': f'v{number}'
                                for number in range(1, 13)})


class DescriptionTest(unittest.TestCase):

    def test_description_of_a_rule_reaches_the_payload(self):
        rules = load_module('rules')
        rules.render_jinja = lambda param, **_kwargs: param
        rule = rules.IdoitVariableRule()
        rule.attributes = {}
        rule.db_host = MagicMock(hostname='srv01')
        outcomes = rule.add_outcomes(
            None, [{'action': 'id_object_description', 'param': 'My text'}], {})

        payload = make_syncer().get_object_payload('srv01', outcomes)
        self.assertEqual(payload['params']['description'], 'My text')

    def test_without_a_rule_the_default_stays(self):
        payload = make_syncer().get_object_payload('srv01', {})
        self.assertEqual(payload['params']['description'], 'undefined')


if __name__ == '__main__':
    unittest.main()
