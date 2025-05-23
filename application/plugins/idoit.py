"""
i-doit
"""
#pylint: disable=too-many-arguments
import pprint
import click
from mongoengine.errors import DoesNotExist

from application import app
from application.modules.idoit.models import IdoitCustomAttributes, IdoitRewriteAttributeRule
from application.modules.idoit.rules import IdoitVariableRule
from application.modules.rule.rewrite import Rewrite
from application.modules.debug import ColorCodes, attribute_table
from application.modules.idoit.syncer import SyncIdoit
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob

def load_rules():
    """
    Load all rules
    """
    #pylint: disable=no-member
    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'idoit_rewrite'
    attribute_rewrite.rules = \
                    IdoitRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

    idoit_rules = IdoitVariableRule()
    idoit_rules.rules = IdoitCustomAttributes.objects(enabled=True).order_by('sort_field')

    return {
        'rewrite' : attribute_rewrite,
        'rules' : idoit_rules,
    }


@app.cli.group(name='i-doit')
def _cli_idoit():
    """
    i-doit Import/ Export
    """


#   .-- Command: import hosts
def import_hosts(account):
    """
    Import hosts from i-doit
    """
    #pylint: disable=no-member, consider-using-generator

    target_config = get_account_by_name(account)
    syncer = SyncIdoit()
    syncer.config = target_config
    syncer.import_hosts()


@_cli_idoit.command('import_hosts')
@click.option("--account")
def cli_import_hosts(account):
    """
    Import hosts from i-doit
    """

    import_hosts(account)
#.


#   .-- Command: export hosts
def export_hosts(account):
    """
    Export hosts to i-doit
    """

    rules = load_rules()

    target_config = get_account_by_name(account)

    syncer = SyncIdoit()
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['rules']
    syncer.config = target_config
    syncer.export_hosts()


@_cli_idoit.command('export_hosts')
@click.option("--account")
def cli_export_hosts(account):
    """
    Export hosts to i-doit
    """

    export_hosts(account)
#.


#   .-- Command: debug hosts
@_cli_idoit.command('debug_host')
@click.argument("hostname")
def idoit_host_debug(hostname):
    """
    Debug host rules
    """

    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")

    rules = load_rules()

    syncer = SyncIdoit()
    syncer.debug = True

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['rules'].debug=True
    syncer.actions = rules['rules']

    try:
        db_host = Host.objects.get(hostname=hostname)
        for key in list(db_host.cache.keys()):
            if key.lower().startswith('idoit'):
                del db_host.cache[key]
        db_host.save()
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return

    attributes = syncer.get_attributes(db_host, 'netbox')

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY Global RULE{ColorCodes.ENDC}")
        return

    rules = syncer.get_host_data(db_host, attributes['all'])
    if rules.get('ignore_host'):
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY local RULE{ColorCodes.ENDC}")
        return

    pprint.pprint(syncer.get_object_payload(db_host, rules))

    attribute_table("Full Attribute List", attributes['all'])
    attribute_table("Filtered Attribute for i-doit Rules", attributes['filtered'])
    attribute_table("Attributes for Rules ", rules)
#.

register_cronjob('i-doit: Import hosts', import_hosts)
register_cronjob('i-doit: Export hosts', export_hosts)
