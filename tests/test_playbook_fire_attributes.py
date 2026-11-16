"""
Playbook fire rules match on the attributes the Ansible inventory of
their project has for a host: labels, inventory data, templates, custom
attributes and rewrites, not on the labels alone.
"""
# pylint: disable=missing-function-docstring
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.plugins.ansible import playbook_rules


def _fire_rule(tag, value):
    """A per host fire rule starting site.yml when tag equals value."""
    doc = SimpleNamespace(rule_source=None, list_source=None)
    doc.to_mongo = lambda: {
        'name': 'fire', '_id': 'fire', 'condition_typ': 'all',
        'conditions': [{'match_type': 'tag', 'tag': tag, 'tag_match': 'equal',
                        'tag_match_negate': False, 'value': value,
                        'value_match': 'equal', 'value_match_negate': False}],
        'outcomes': [{'playbook': 'site.yml'}], 'last_match': False,
    }
    return doc


class TestPlaybookFireAttributes(unittest.TestCase):
    """Which attributes a fire rule sees"""

    def _fire(self, rule, attributes):
        """Fire `rule` against srv01, whose inventory has `attributes`."""
        db_host = SimpleNamespace(hostname='srv01', labels={'os': 'linux'})
        syncer = Mock(cache_key='ansible_Default')
        syncer.get_attributes.return_value = attributes
        query = Mock()
        query.order_by.return_value = [rule]
        with patch.object(playbook_rules, 'AnsiblePlaybookFireRule') as model, \
                patch.object(playbook_rules, 'Host') as host, \
                patch.object(playbook_rules, '_syncers_per_project',
                             return_value=[(syncer, [rule])]), \
                patch.object(playbook_rules, 'available_playbooks',
                             return_value=['site.yml']), \
                patch.object(playbook_rules, '_already_fired', return_value=False), \
                patch.object(playbook_rules, 'run_playbook') as run:
            model.objects.return_value = query
            host.get_export_hosts.return_value = [db_host]
            fired = playbook_rules.fire_playbook_rules()
        syncer.get_attributes.assert_called_once_with(db_host, 'ansible_Default')
        return fired, run

    def test_inventory_data_matches(self):
        fired, run = self._fire(_fire_rule('cmk_agent_version', '2.4'),
                                {'all': {'os': 'linux', 'cmk_agent_version': '2.4'},
                                 'filtered': {}})
        self.assertEqual(fired, 1)
        self.assertEqual(run.call_args.kwargs['target_host'], 'srv01')

    def test_a_host_the_project_filter_drops_fires_nothing(self):
        fired, run = self._fire(_fire_rule('os', 'linux'), False)
        self.assertEqual(fired, 0)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
