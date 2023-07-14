"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
import json
import click
import importlib
from ast import literal_eval

from mongoengine.errors import NotUniqueError
from application import app

from application.modules.rule.models import CustomAttribute, FullCondition, FilterAction

enabled_rules = {
    'ansible_customvars': ('application.modules.ansible.models', 'AnsibleCustomVariablesRule')
}


def export_rules_from_model(rule_type):
    """
    Export Given Rulesets
    """
    model = importlib.import_module(enabled_rules[rule_type][0])
    for db_rule in getattr(model, enabled_rules[rule_type][1]).objects():
        yield db_rule.to_json()


def import_rules_to_model(rule_type, json_raw):
    """
    Import Rules to Model
    """
    model = importlib.import_module(enabled_rules[rule_type][0])
    for json_rule_raw in json_raw:
        json_dict = json.loads(json_rule_raw)
        print(f"* Import {json_dict['name']}")
        db_ref = getattr(model, enabled_rules[rule_type][1])()
        new = db_ref.from_json(json.dumps(json_dict))
        try:
            new.save(force_insert=True)
        except NotUniqueError:
            print("   Already existed")

@app.cli.group(name='rules')
def cli_rules():
    """Rule related commands"""

@cli_rules.command('export_rules')
@click.argument("rule_type", default="")
def export_rules(rule_type):
    """
    Export Rules by Category
    """
    if rule_type.lower() in enabled_rules:
        rules = list(export_rules_from_model(rule_type))
        print({'rule_type': rule_type,
               'rules_json': rules})
    else:
        print("Ruletype not supported")
        print(f"Currently supported: {','.join(enabled_rules.keys())}")

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer
    """
    with open(rulefile_path, newline='', encoding='utf-8') as rulefile:
        rules_obj = literal_eval(rulefile.read())
        rule_type = rules_obj['rule_type']
        rule_json_field = rules_obj['rules_json']
        if rule_type not in enabled_rules:
            print("Ruletype not supported")
            print(f"Currently supported: {','.join(enabled_rules.keys())}")
        else:
            import_rules_to_model(rule_type, rule_json_field)
