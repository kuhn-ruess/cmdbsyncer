"""
Handle Netbox
"""
#pylint: disable=no-member, too-many-locals
import click
from mongoengine.errors import DoesNotExist

from application import app
from application.modules.debug import attribute_table

from application.modules.rule.rewrite import Rewrite

from application.modules.netbox.models import *
from application.modules.netbox.rules import *

from application.modules.netbox.devices import SyncDevices
from application.modules.netbox.vms import SyncVMS
from application.modules.netbox.ipam import SyncIPAM
from application.modules.netbox.interfaces import SyncInterfaces
from application.modules.netbox.contacts import SyncContacts

from syncerapi.v1 import (
    register_cronjob,
    cc,
    Host,
)

def load_device_rules():
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
    """Netbox Import and Syncronisation"""


#   .-- Command: Export Hosts
def netbox_device_export(account):
    """Sync Objects with Netbox"""
    try:
        rules = load_device_rules()
        syncer = SyncDevices(account)
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']
        syncer.actions = rules['actions']
        syncer.name = "Export Devices"
        syncer.source = "netbox_device_export"
        syncer.export_hosts()
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_hosts')
@cli_netbox.command('export_devices')
@click.argument("account")
def cli_netbox_device_export(account):
    """Sync Devices with Netbox"""
    netbox_device_export(account)
#.


#   .-- Command: Import Devices
def netbox_device_import(account):
    """Import Devices from Netbox"""
    try:
        syncer = SyncDevices(account)
        syncer.import_hosts()
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('import_hosts')
@cli_netbox.command('import_devices')
@click.argument("account")
def cli_netbox_device_import(account):
    """Import Devices from Netbox"""
    netbox_device_import(account)
#.

#   .-- Command: Import VMS
def netbox_vm_import(account):
    """Import VMs from Netbox"""
    try:
        syncer = SyncVMS(account)
        syncer.import_hosts()
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('import_vms')
@click.argument("account")
def cli_netbox_vm_import(account):
    """Import VMs from Netbox"""
    netbox_vm_import(account)
#.

#   .-- Command: Export IPs
def netbox_ip_sync(account):
    """Import Devices from Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')
        
        netbox_rules = NetboxIpamIPaddressRule()
        netbox_rules.rules = NetboxIpamIpaddressattributes.objects(enabled=True).order_by('sort_field')

        syncer = SyncIPAM(account)
        syncer.rewrite = attribute_rewrite
        syncer.actions = netbox_rules
        syncer.name = "Export IPs"
        syncer.source = "netbox_ipam_export"

        syncer.sync_ips()
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_ips')
@click.argument("account")
def cli_netbox_ip_syn(account):
    """Export IPAM IPs"""
    netbox_ip_sync(account)
#.

#   .-- Command: Export Interfaces
def netbox_interface_sync(account):
    """Export Interfaces to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')
        
        netbox_rules = NetboxDevicesInterfaceRule()
        netbox_rules.rules = NetboxDcimInterfaceAttributes.objects(enabled=True).order_by('sort_field')

        syncer = SyncInterfaces(account)
        syncer.rewrite = attribute_rewrite
        syncer.actions = netbox_rules
        syncer.name = "Export Interfaces"
        syncer.source = "netbox_interface_export"

        syncer.sync_interfaces()
    except KeyError as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_interfaces')
@click.argument("account")
def cli_netbox_interface(account):
    """Export Interfaces of Devices"""
    netbox_interface_sync(account)
#.
#   .-- Command: Export Contacts
def netbox_contacts_sync(account):
    """Export Contacts to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')
        
        netbox_rules = NetboxContactRule()
        netbox_rules.rules = NetboxContactAttributes.objects(enabled=True).order_by('sort_field')

        syncer = SyncContacts(account)
        syncer.rewrite = attribute_rewrite
        syncer.actions = netbox_rules
        syncer.name = "Export Interfaces"
        syncer.source = "netbox_contacts_export"

        syncer.sync_contacts()
    except KeyError as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_contacts')
@click.argument("account")
def cli_netbox_contacts(account):
    """Export Contacts"""
    netbox_contacts_sync(account)
#.


#   .-- Command: Debug Hosts
@cli_netbox.command('debug_host')
@click.argument("hostname")
def netbox_host_debug(hostname):
    """Debug Host Rules"""
    print(f"{cc.HEADER} ***** Run Rules ***** {cc.ENDC}")

    rules = load_device_rules()

    syncer = SyncDevices(False)
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
        if "CustomAttributeRule" in db_host.cache:
            del db_host.cache['CustomAttributeRule']
        db_host.save()
    except DoesNotExist:
        print(f"{cc.FAIL}Host not Found{cc.ENDC}")
        return


    attributes = syncer.get_host_attributes(db_host, 'netbox')

    if not attributes:
        print(f"{cc.FAIL}THIS HOST IS IGNORED BY RULE{cc.ENDC}")
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

register_cronjob("Netbox: Export Devices", netbox_device_export)
register_cronjob("Netbox: Import Devices", netbox_device_import)
register_cronjob("Netbox: Import VMs", netbox_vm_import)
register_cronjob("Netbox: Export IPs", netbox_ip_sync)
register_cronjob("Netbox: Export Contacts", netbox_contacts_sync)
