"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
import json
import click
from mongoengine.errors import NotUniqueError

from application import app

from application.modules.ansible.models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                                               AnsibleCustomVariablesRule

from application.modules.rule.models import CustomAttribute, FullCondition, FilterAction



def export_ansible():
    """
    @TODO: Move to Modules
    """
    for db_rule in AnsibleCustomVariablesRule.objects():
        print(db_rule)

@app.cli.group(name='rules')
def cli_rules():
    """Rule related commands"""

@cli_rules.command('export_rules')
@click.argument("rule_category")
def export_rules(rule_category):
    """
    Export Rules by Category
    """
    categories = {
        'ansible': export_ansible,
    }
    if rule_category.lower() in categories:
        categories[rule_category.lower()]()
    else:
        print("Ruletype not supported")
        print(f"Currently supported: {','.join(categories.keys())}")

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer
    """
    supported_rules = {
        'AnsibleCustomVariablesRule': AnsibleCustomVariablesRule
    }
    with open(rulefile_path, newline='', encoding='utf-8') as rulefile:
        for json_rule in json.load(rulefile):
            print(f"Import: {json_rule['rule_name']}")
            new_rule = supported_rules[json_rule['rule_type']]()
            new_rule.name = json_rule['rule_name']
            new_rule.condition_typ = json_rule['condition_typ']
            new_rule.enabled = False
            new_rule.sort_field = json_rule['sort_field']
            conditions = []
            for cond in json_rule['conditions']:
                if cond['type'] == 'label':
                    condition = FullCondition()
                    condition.match_type = 'tag'
                    condition.tag_match = cond['tag'][0]
                    condition.tag = cond['tag'][1]
                    condition.value_match = cond['value'][0]
                    condition.value = cond['value'][1]
                    conditions.append(condition)
            new_rule.conditions = conditions
            outcomes = []
            for out in json_rule['outcomes']:
                attribute = CustomAttribute()
                attribute.attribute_name = out[0]
                attribute.attribute_value = out[1]
                outcomes.append(attribute)
            new_rule.outcomes = outcomes
            try:
                new_rule.save()
            except NotUniqueError:
                print(" -- Already existed")
