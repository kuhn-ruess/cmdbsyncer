#!/usr/bin/env python3
"""VMware Support"""
import click

from application import app, logger
from application.modules.rule.rewrite import Rewrite
from application.helpers.plugins import register_cli_group

from syncerapi.v1 import (
    register_cronjob,
)

from .models import (
        VMwareRewriteAttributes,
        VMwareCustomAttributes,

        )

from .custom_attributes import (
        VMwareCustomAttributesPlugin,
        )

from .rules import VmwareCustomAttributesRule

cli_vmware = register_cli_group(app, 'vmware', 'vmware', "VMware commands")


#   .-- Debug Data — shared backend for the HTML debug page
# pylint: disable=import-outside-toplevel
def get_vmware_debug_data(hostname):
    """Return `(attributes, extra_attributes, rule_logs)` for the HTML
    debug view. VMware has rewrite + custom-attribute rules but no
    filter — same shape as Netbox.

    The extra imports are deliberate: keeping them at the top would
    create an import cycle with `application.modules.plugin`, and we
    only need them on the debug path.
    """
    from mongoengine.errors import DoesNotExist as _DoesNotExist
    from application.models.host import Host
    from application.modules.plugin import Plugin

    try:
        db_host = Host.objects.get(hostname=hostname)
    except _DoesNotExist:
        return None, None, None

    # Drop cached vmware_* entries so rules actually re-evaluate.
    for key in list(db_host.cache.keys()):
        if key.lower().startswith('vmware'):
            del db_host.cache[key]
    db_host.save()

    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'vmware_rewrite'
    attribute_rewrite.debug = True
    attribute_rewrite.rules = \
        VMwareRewriteAttributes.objects(enabled=True).order_by('sort_field')

    actions = VmwareCustomAttributesRule()
    actions.debug = True
    actions.rules = \
        VMwareCustomAttributes.objects(enabled=True).order_by('sort_field')

    # Evaluate rewrite + actions against the host's labels without
    # needing a real vCenter connection. The Plugin base exposes the
    # same get_attributes/get_host_data shape every syncer uses.
    syncer = Plugin()
    syncer.rewrite = attribute_rewrite
    syncer.actions = actions
    syncer.name = 'vmware-debug'
    syncer.source = 'vmware_debug'

    attributes = syncer.get_attributes(db_host, 'vmware')
    extra_attributes = {}
    if attributes:
        extra_attributes = syncer.get_host_data(db_host, attributes['all']) or {}

    rule_logs = {
        'rewrite': attribute_rewrite.debug_lines,
        'actions': actions.debug_lines,
    }
    return attributes, extra_attributes, rule_logs

#   .-- Custom Attributes
def custom_attributes_export(account, debug=False):
    """
    Custom Attributes Export
    """
    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'vmware_rewrite'

    attribute_rewrite.rules = \
            VMwareRewriteAttributes.objects(enabled=True).order_by('sort_field')

    rules = VmwareCustomAttributesRule()
    rules.rules = VMwareCustomAttributes.objects(enabled=True).order_by('sort_field')

    try:
        vm = VMwareCustomAttributesPlugin(account)
        vm.rewrite = attribute_rewrite
        vm.actions = rules

        vm.name = f"Export Attributes for {account}"
        vm.source = "vmware_attribute_export"
        vm.export_attributes()
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Log and re-raise so cron runs record the failure and exit
        # non-zero instead of appearing to succeed while doing nothing.
        logger.exception("VMware export_custom_attributes failed: %s", error)
        if not debug:
            print(f"VMware export_custom_attributes failed: {error}")
        raise

def custom_attributes_inventorize(account, debug=False):
    """
    Custom Attribute Inventorize
    """
    try:
        vm = VMwareCustomAttributesPlugin(account)
        vm.name = f"Inventorize data from {account}"
        vm.source = "vmware_attribute_inventorize"
        vm.inventorize_attributes()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.exception("VMware inventorize_custom_attributes failed: %s", error)
        if not debug:
            print(f"VMware inventorize_custom_attributes failed: {error}")
        raise

@cli_vmware.command('export_custom_attributes')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_custom_attributes_export(account, debug):
    """Export Custom Attributes"""
    custom_attributes_export(account, debug)

@cli_vmware.command('inventorize_custom_attributes')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_inventorize_custom_attributes(account, debug):
    """Inventorize Custom Attributes from VMware"""
    custom_attributes_inventorize(account, debug)


register_cronjob("VMware: Export Custom Attributes", custom_attributes_export)
register_cronjob("VMware: Inventorize Custom Attributes", custom_attributes_inventorize)
#.
