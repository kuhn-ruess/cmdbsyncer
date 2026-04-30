"""
i-doit
"""
import pprint
import click
from mongoengine.errors import DoesNotExist

from application import app
from application.modules.rule.rewrite import Rewrite
from application.modules.debug import ColorCodes, attribute_table
from application.models.host import Host
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .models import IdoitCustomAttributes, IdoitRewriteAttributeRule
from .rules import IdoitVariableRule
from .syncer import SyncIdoit

def load_rules():
    """
    Load all rules
    """
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


_cli_idoit = register_cli_group(app, 'i-doit', 'idoit', "i-doit Import/ Export")


#   .-- Command: import hosts
def import_hosts(account, debug=False):
    """
    Import hosts from i-doit
    """

    syncer = SyncIdoit(account)
    syncer.debug = debug
    syncer.import_hosts()


@_cli_idoit.command('import_hosts')
@click.option("--account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts(account, debug):
    """
    Import hosts from i-doit
    """

    import_hosts(account, debug)

#.
#   .-- Command: export hosts
def export_hosts(account):
    """
    Export hosts to i-doit
    """

    rules = load_rules()

    syncer = SyncIdoit(account)
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['rules']
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
