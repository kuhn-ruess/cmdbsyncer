"""
Handle Netbox
"""
#pylint: disable=no-member, too-many-locals
#pylint: disable=wildcard-import, unused-wildcard-import
import click
from mongoengine.errors import DoesNotExist

from application import app
from application import log

from application.modules.rule.rewrite import Rewrite

from application.modules.netbox.models import *
from application.modules.netbox.rules import *

from application.modules.netbox.devices import SyncDevices
from application.modules.netbox.ips import SyncIPS
from application.modules.netbox.interfaces import SyncInterfaces, SyncVirtInterfaces
from application.modules.netbox.contacts import SyncContacts
from application.modules.netbox.dataflow import SyncDataFlow
from application.modules.netbox.cluster import SyncCluster
from application.modules.netbox.virtualmachines import SyncVirtualMachines
from application.modules.netbox.prefixes import SyncPrefixes
from application.modules.debug import attribute_table

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

#   .-- Command: Export Devices
def netbox_device_export(account, debug=False, debug_rules=False):
    """Export DCIM Devices"""
    if debug_rules:
        netbox_host_debug(debug_rules)
        return
    try:
        rules = load_device_rules()
        syncer = SyncDevices(account)
        syncer.debug = debug
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']
        syncer.actions = rules['actions']
        syncer.name = "Netbox: Update Devices"
        syncer.source = "netbox_device_sync"
        syncer.export_hosts()
    except Exception as error_obj: #pylint: disable=broad-except
        if debug:
            raise
        log.log(f"Export Devices to Account: {account} Failed",
        source="netbox_device_sync_command", details=[('error', str(error_obj))])
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_devices')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_device_export(account, debug, debug_rules):
    """Export Devices"""
    netbox_device_export(account, debug, debug_rules)
register_cronjob("Netbox: Update Devices", netbox_device_export)
#.
#   . -- Command: Export Virtual Machines
def netbox_virtual_machines_sync(account, debug=False, debug_rules=False):
    """Export Virtual Machines to NB"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxVirutalMachineRule()
        netbox_rules.rules = \
                NetboxVirtualMachineAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncVirtualMachines(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update VMs"
            syncer.source = "netbox_vm_sync"
            syncer.sync_virtualmachines()
        else:
            syncer = SyncVirtualMachines(False)
            syncer.debug = True
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'netbox')
    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_vms')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_vms(account, debug, debug_rules):
    """Export Virtual Machines"""
    netbox_virtual_machines_sync(account, debug, debug_rules)

register_cronjob("Netbox: Sync Virutal Machines", netbox_virtual_machines_sync)
#.
#   . -- Command: Export Cluster
def netbox_cluster_sync(account, debug=False, debug_rules=False):
    """Export Clusters to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxCluserRule()
        netbox_rules.rules = \
                NetboxClusterAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncCluster(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update Cluster"
            syncer.source = "netbox_cluster_sync"
            syncer.sync_clusters()
        else:
            syncer = SyncCluster(False)
            syncer.debug = True
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'netbox')
    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_cluster')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_cluster(account, debug, debug_rules):
    """Export Cluster """
    netbox_cluster_sync(account, debug, debug_rules)

register_cronjob("Netbox: Sync Cluster", netbox_cluster_sync)
#.
#   .-- Command: Import VMS
def netbox_device_import(account, debug=False):
    """Import Devices from Netbox"""
    try:
        syncer = SyncDevices(account)
        syncer.debug = debug
        syncer.import_hosts()
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('import_devices')
@click.option("--debug", is_flag=True)
@click.argument("account")
def cli_netbox_device_import(account, debug=False):
    """Import Devices from Netbox"""
    netbox_device_import(account, debug)
register_cronjob("Netbox: Import Devices", netbox_device_import)
#.
#   .-- Command: Import VMS
def netbox_vm_import(account, debug=False):
    """Import VMs from Netbox"""
    try:
        syncer = SyncVirtualMachines(account)
        syncer.debug = debug
        syncer.import_hosts()
    except Exception as error_obj: #pylint:disable=broad-except
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')
        if debug:
            raise

@cli_netbox.command('import_vms')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cli_netbox_vm_import(account, debug=False):
    """Import VMs from Netbox"""
    netbox_vm_import(account, debug)
register_cronjob("Netbox: Import VMs", netbox_vm_import)
#.
#   .-- Command: Export IPs
def netbox_ip_sync(account, debug=False, debug_rules=False):
    """Import Devices from Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxIpamIPaddressRule()
        netbox_rules.rules = \
                NetboxIpamIpaddressattributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncIPS(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update IPs"
            syncer.source = "netbox_ipam_ip_export"
            syncer.sync_ips()
        else:
            syncer = SyncIPS(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_ips')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_ip_syn(account, debug, debug_rules):
    """Export IPAM IPs"""
    netbox_ip_sync(account, debug, debug_rules)
register_cronjob("Netbox: Update IPs", netbox_ip_sync)
#.
#   .-- Command: Export Prefixes
def netbox_prefix_sync(account, debug=False, debug_rules=False):
    """Export Prefixes to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxIpamPrefixRule()
        netbox_rules.rules = \
                NetboxIpamPrefixAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncPrefixes(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update Prefixes"
            syncer.source = "netbox_ipam_prefix_export"
            syncer.sync_prefixes()
        else:
            syncer = SyncPrefixes(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_prefixes')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_prefix_syn(account, debug, debug_rules):
    """Export IPAM IPs"""
    netbox_prefix_sync(account, debug, debug_rules)
register_cronjob("Netbox: Update Prefixes", netbox_prefix_sync)
#.
#   .-- Command: Export Interfaces
def netbox_interface_sync(account, debug=False, debug_rules=False):
    """Export DCIM Interfaces"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxInterfaceRule()
        netbox_rules.rules = \
                NetboxDcimInterfaceAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncInterfaces(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update Interfaces"
            syncer.source = "netbox_dcim_interface_sync"
            syncer.sync_interfaces()
        else:
            syncer = SyncInterfaces(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')
    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_dcim_interfaces')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_interface(account, debug, debug_rules):
    """Export Interfaces of Devices"""
    netbox_interface_sync(account, debug, debug_rules)

register_cronjob("Netbox: Update DCIM Interfaces", netbox_interface_sync)


def netbox_virt_interface_sync(account, debug=False, debug_rules=False):
    """Export Virtualization Interfaces"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxVirtInterfaceRule()
        netbox_rules.rules = \
                NetboxVirtualizationInterfaceAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncVirtInterfaces(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update Interfaces"
            syncer.source = "netbox_virt_interface_sync"
            syncer.sync_interfaces(mode='virtualization')
        else:
            syncer = SyncVirtInterfaces(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')
    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_virt_interfaces')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_virt_interface(account, debug, debug_rules):
    """Export Interfaces of Virtual Machines"""
    netbox_virt_interface_sync(account, debug, debug_rules)

register_cronjob("Netbox: Update Virtualization Interfaces", netbox_virt_interface_sync)

#.
#   .-- Command: Export Contacts
def netbox_contacts_sync(account, debug=False, debug_rules=False):
    """Export Contacts to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxContactRule()
        netbox_rules.rules = NetboxContactAttributes.objects(enabled=True).order_by('sort_field')

        if not debug_rules:
            syncer = SyncContacts(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update Contacts"
            syncer.source = "netbox_contact_sync"
            syncer.sync_contacts()
        else:
            syncer = SyncContacts(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')
    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_contacts')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_contacts(account, debug, debug_rules):
    """Export Contacts"""
    netbox_contacts_sync(account, debug, debug_rules)
register_cronjob("Netbox: Update Contacts", netbox_contacts_sync)
#.
#   .-- Command: Export Dataflow
def netbox_dataflow_sync(account, debug=False, debug_rules=False):
    """Export DataFlow Data to Netbox"""
    try:
        attribute_rewrite = Rewrite()
        attribute_rewrite.cache_name = 'netbox_rewrite'

        attribute_rewrite.rules = \
                NetboxRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

        netbox_rules = NetboxDataflowRule()
        netbox_rules.rules = NetboxDataflowAttributes.objects(enabled=True).order_by('sort_field')
        if not debug_rules:
            syncer = SyncDataFlow(account)
            syncer.debug = debug
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.name = "Netbox: Update DataFlow Data"
            syncer.source = "netbox_dataflow_sync"
            syncer.sync_dataflow()
        else:
            syncer = SyncDataFlow(False)
            syncer.rewrite = attribute_rewrite
            syncer.actions = netbox_rules
            syncer.debug_rules(debug_rules, 'Netbox')

    except KeyError as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Missing Field: {error_obj} {cc.ENDC}')
    except Exception as error_obj: #pylint:disable=broad-except
        if debug:
            raise
        print(f'{cc.FAIL}Connection Error: {error_obj} {cc.ENDC}')

@cli_netbox.command('export_dataflow')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument("account")
def cli_netbox_dataflow(account, debug, debug_rules):
    """Export Dataflow"""
    netbox_dataflow_sync(account, debug, debug_rules)
register_cronjob("Netbox: Update Dataflow", netbox_dataflow_sync)
#.
#   .-- Command: Debug Hosts
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
#.
