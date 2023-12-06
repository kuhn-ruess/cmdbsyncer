"""
Handle Netbox
"""
#pylint: disable=no-member, too-many-locals
import click
from mongoengine.errors import DoesNotExist

from application.models.host import Host
from application import app
from application.modules.debug import ColorCodes, attribute_table
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob

from application.modules.rule.rewrite import Rewrite

from application.modules.netbox.models import NetboxCustomAttributes, NetboxRewriteAttributeRule
from application.modules.netbox.rules import NetboxVariableRule
from application.modules.netbox.syncer import SyncNetbox

def load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = False

    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'netbox_rewrite'

    attribute_rewrite.rules = \
            NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

    netbox_rules = NetboxVariableRule()
    netbox_rules.rules = NetboxCustomAttributes.objects(enabled=True).order_by('sort_field')

    return {
        'filter': attribute_filter,
        'rewrite': attribute_rewrite,
        'actions': netbox_rules,
    }

@app.cli.group(name='netbox')
def cli_netbox():
    """Netbox Commands"""


#   .-- Command: Export Hosts
def netbox_host_export(account, debug):
    """Sync Objects with Netbox"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = load_rules()
            syncer = SyncNetbox(debug)
            syncer.filter = rules['filter']
            syncer.rewrite = rules['rewrite']
            syncer.actions = rules['actions']
            syncer.config = target_config
            syncer.export_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{ColorCodes.FAIL}Connection Error: {error_obj} {ColorCodes.ENDC}')
        raise
@cli_netbox.command('export_hosts')
@click.argument("account")
@click.option("-d", "--debug", default=False, is_flag=True)
def cli_netbox_host_export(account, debug):
    """Sync Objects with Netbox"""
    netbox_host_export(account, debug)
#.
#   .-- Command: Import Hosts
def netbox_host_import(account):
    """Import Devices from Netbox"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncNetbox(False)
            syncer.config = target_config
            syncer.import_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'C{ColorCodes.FAIL}Connection Error: {error_obj} {ColorCodes.ENDC}')
@cli_netbox.command('import_hosts')
@click.argument("account")
def cli_netbox_host_import(account):
    """Import Devices from Netbox"""
    netbox_host_import(account)
#.
#   .-- Command: Debug Hosts
@cli_netbox.command('debug_host')
@click.argument("hostname")
def netbox_host_debug(hostname):
    """Debug Host Rules"""
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")

    rules = load_rules()

    syncer = SyncNetbox(False)
    syncer.debug = True
    syncer.config = {
        '_id': "debugmode",
    }

    if rules['filter']:
        rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    try:
        db_host = Host.objects.get(hostname=hostname)
        for key in list(db_host.cache.keys()):
            if key.lower().startswith('netbox'):
                del db_host.cache[key]
        db_host.save()
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return


    attributes = syncer.get_host_attributes(db_host, 'netbox')

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])

    attribute_table("Full Attribute List", attributes['all'])
    attribute_table("Filtered Attribute for Netbox Rules", attributes['filtered'])
    attribute_table("Attributes by Rule ", extra_attributes)
    if 'update_interfaces' in extra_attributes:
        attribute_table("Interfaces", {y['portName']: y for x,y in \
                syncer.get_interface_list_by_attributes(attributes['all']).items()})

    ## Disabled because fails in case of attribute sync, payload method tries to create them
    #payload = syncer.get_payload(db_host, extra_attributes, attributes['all'])
    #attribute_table("API Payload", payload)
#.

register_cronjob("Netbox: Export Hosts", netbox_host_export)
register_cronjob("Netbox: Import Hosts", netbox_host_import)
