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

from application.modules.rule.rewrite import Rewrite
from application.modules.rule.filter import Filter

from application.modules.netbox.models import NetboxCustomAttributes, NetboxRewriteAttributeRule,\
                                              NetboxFilterRule
from application.modules.netbox.rules import NetboxVariableRule
from application.modules.netbox.syncer import SyncNetbox

def load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = Filter()
    attribute_filter.rules = NetboxFilterRule.objects(enabled=True).order_by('sort_field')

    attribute_rewrite = Rewrite()
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
@cli_netbox.command('export_hosts')
@click.argument("account")
def netbox_host_export(account):
    """Sync Objects with Netbox"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = load_rules()
            syncer = SyncNetbox()
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
#.
#   .-- Command: Import Hosts
@cli_netbox.command('import_hosts')
@click.argument("account")
def netbox_host_import(account):
    """Import Devices from Netbox"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncNetbox()
            syncer.config = target_config
            syncer.import_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'C{ColorCodes.FAIL}Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Command: Debug Hosts
@cli_netbox.command('debug_host')
@click.argument("hostname")
def netbox_host_debug(hostname):
    """Debug Host Rules"""
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")

    rules = load_rules()

    syncer = SyncNetbox()
    syncer.debug = True
    rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return

    attributes = syncer.get_host_attributes(db_host)

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])

    attribute_table("Full Attribute List", attributes['all'])
    attribute_table("Filtered Attribute for Netbox Rules", attributes['filtered'])
    attribute_table("Attributes by Rule ", extra_attributes)
    if 'update_interfaces' in extra_attributes:
        attribute_table("Interfaces", {y['portName']: y for x,y in syncer.get_interface_list_by_attributes(attributes['all']).items()})


