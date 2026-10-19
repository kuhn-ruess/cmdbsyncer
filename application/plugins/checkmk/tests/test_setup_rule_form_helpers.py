"""
Setup Rule helpers behind the form: the HOST_FOLDER placeholder the export
hands a per host rule, and the suggestions of the label condition editor.
"""
# pylint: disable=missing-function-docstring,protected-access
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from application.plugins.checkmk import cmk_rules
from tests import make_checkmk_rule_sync


class TestWithHostFolder(unittest.TestCase):
    """CheckmkRuleSync._with_host_folder"""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.attributes = {'all': {'HOSTNAME': 'srv01'}, 'filtered': {}}

    def _run(self, folder_template):
        actions = {'checkgroup_parameters:filesystem': [
            {'ruleset': 'checkgroup_parameters:filesystem',
             'folder': folder_template, 'value_template': '{}'}]}
        with patch('application.plugins.checkmk.rules.host_folder_engine',
                   return_value='engine') as engine, \
                patch('application.plugins.checkmk.rules.host_folder',
                      return_value='/linux/web') as folder:
            result = self.sync._with_host_folder('db_host', actions,
                                                 self.attributes)
        return result, engine, folder

    def test_outcome_without_placeholder_runs_no_folder_rules(self):
        result, engine, folder = self._run('/linux')
        self.assertIs(result, self.attributes)
        engine.assert_not_called()
        folder.assert_not_called()

    def test_placeholder_gets_the_host_folder(self):
        result, _engine, folder = self._run('{{ HOST_FOLDER }}')
        self.assertEqual(result['all']['HOST_FOLDER'], '/linux/web')
        self.assertEqual(result['all']['HOSTNAME'], 'srv01')
        folder.assert_called_once_with('engine', 'db_host', self.attributes['all'])
        # The host's own attribute dict stays as it is.
        self.assertNotIn('HOST_FOLDER', self.attributes['all'])

    def test_folder_engine_is_built_once(self):
        self._run('{{ HOST_FOLDER }}')
        _result, engine, _folder = self._run('{{ HOST_FOLDER }}/sub')
        engine.assert_not_called()


def _rule(*outcomes):
    return SimpleNamespace(outcomes=[SimpleNamespace(**o) for o in outcomes])


class TestLabelSuggestions(unittest.TestCase):
    """label_suggestions and the label conditions of the Setup Rules"""

    def setUp(self):
        models = sys.modules['application.plugins.checkmk.models']
        rules = [
            _rule({'condition_label_template': 'os:linux',
                   'condition_service_label': 'team:web, tier:{{ tier }}'}),
            _rule({'condition_label_template': '{{ site }}:yes',
                   'condition_service_label': ''},
                  {'condition_label_template': 'os:windows',
                   'condition_service_label': None}),
        ]
        model = MagicMock()
        model.objects.only.return_value = rules
        patcher = patch.object(models, 'CheckmkRuleMngmt', model, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_service_keys_and_values_from_the_rules(self):
        self.assertEqual(cmk_rules.label_suggestions('service'), ['team'])
        self.assertEqual(cmk_rules.label_suggestions('service', 'team'), ['web'])

    @patch.object(cmk_rules, '_host_label_keys', return_value={'dc', 'OS'})
    def test_host_keys_add_the_host_attributes(self, _keys):
        self.assertEqual(cmk_rules.label_suggestions('host'), ['dc', 'OS', 'os'])

    @patch.object(cmk_rules, '_host_label_values', return_value={'mac'})
    def test_host_values_of_a_key(self, values):
        self.assertEqual(cmk_rules.label_suggestions('host', ' os '),
                         ['linux', 'mac', 'windows'])
        values.assert_called_once_with('os')

    @patch.object(cmk_rules, '_host_label_values')
    def test_keys_a_mongo_path_cannot_hold_get_nothing(self, values):
        for key in ('a.b', '$where', ''):
            self.assertEqual(cmk_rules.label_suggestions('host', key), [])
        values.assert_not_called()

    def test_unknown_kind(self):
        self.assertEqual(cmk_rules.label_suggestions('tag'), [])


if __name__ == '__main__':
    unittest.main()
