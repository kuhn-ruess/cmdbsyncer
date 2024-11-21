"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
import json
from json.decoder import JSONDecodeError
import importlib
from ast import literal_eval
import click

from mongoengine.errors import NotUniqueError
from application import app

enabled_rules = {
    'ansible_customvars': ('application.modules.ansible.models', 'AnsibleCustomVariablesRule'),
    'custom_attributes': ('application.modules.custom_attributes.models', 'CustomAttributeRule'),
    'cmk_tags': ('application.modules.checkmk.models', 'CheckmkTagMngmt'),
    'cmk_filter': ('application.modules.checkmk.models', 'CheckmkFilterRule'),
    'cmk_inventory': ('application.modules.checkmk.models', 'CheckmkInventorizeAttributes'),
    'cmk_export_rules': ('application.modules.checkmk.models', 'CheckmkRule'),
    'cmk_rules': ('application.modules.checkmk.models', 'CheckmkRuleMngmt'),
    'cmk_groups': ('application.modules.checkmk.models', 'CheckmkGroupRule'),
    'cmk_user': ('application.modules.checkmk.models', 'CheckmkUserMngmt'),
    'cmk_rewrite': ('application.modules.checkmk.models', 'CheckmkRewriteAttributeRule'),
    'cmk_sites': ('application.modules.checkmk.models', 'CheckmkSite'),
    'cmk_site_settings': ('application.modules.checkmk.models', 'CheckmkSettings'),
    'cmk_bi_aggregation': ('application.modules.checkmk.models', 'CheckmkBiAggregation'),
    'cmk_bi_rule': ('application.modules.checkmk.models', 'CheckmkBiRule'),
    'cmk_downtimes': ('application.modules.checkmk.models', 'CheckmkDowntimeRule'),
    'host_objects': ('application.models.host', 'Host'),
    'accounts': ('application.models.account', 'Account'),
    'idoit_rules': ('application.modules.idoit.models', 'IdoitCustomAttributes'),
    'netbox_interfaces': ('application.modules.netbox.models', 'NetboxDcimInterfaceAttributes'),
    'netbox_devices': ('application.modules.netbox.models', 'NetboxCustomAttributes'),
}


def export_rules_from_model(rule_type):
    """
    Export Given Rulesets
    """
    model = importlib.import_module(enabled_rules[rule_type][0])
    for db_rule in getattr(model, enabled_rules[rule_type][1]).objects():
        yield db_rule.to_json()

@app.cli.group(name='rules')
def cli_rules():
    """Syner Rules import and Export"""

@cli_rules.command('export_rules')
@click.argument("rule_type", default="")
def export_rules(rule_type):
    """
    Export Rules by Category
    """
    if rule_type.lower() in enabled_rules:
        print(json.dumps({"rule_type": rule_type}))
        for rule in export_rules_from_model(rule_type):
            print(rule)
    else:
        print("Ruletype not supported")
        print("Currently supported:")
        print()
        for rulename in sorted(enabled_rules):
            print(rulename)

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer
    """
    with open(rulefile_path, encoding='utf-8') as rulefile:
        rule_type = False
        for line in rulefile.readlines():
            try:
                json_dict = json.loads(line)
            except JSONDecodeError:
                print (line)
                continue
            if not rule_type:
                rule_type = json_dict['rule_type']
                if rule_type not in enabled_rules:
                    print("Ruletype not supported")
                    print(f"Currently supported: {', '.join(enabled_rules.keys())}")
                    return
                model = importlib.import_module(enabled_rules[rule_type][0])
            else:
                print(f"* Import {json_dict['_id']}")
                db_ref = getattr(model, enabled_rules[rule_type][1])()
                new = db_ref.from_json(json.dumps(json_dict))
                try:
                    new.save(force_insert=True)
                except NotUniqueError:
                    print("   Already existed")
