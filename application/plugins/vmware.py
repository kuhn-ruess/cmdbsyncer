#!/usr/bin/env python3
"""VMware Support"""
#pylint: disable=logging-fstring-interpolation
import click

from application.modules.rule.rewrite import Rewrite


from application.modules.vmware.models import (
        VMwareRewriteAttributes,
        VMwareCustomAttributes,

        )

from application.modules.vmware.custom_attributes import (
        VMwareCustomAttributesPlugin,
        )

from application.modules.vmware.rules import VmwareCustomAttributesRule

from syncerapi.v1 import (
    register_cronjob,
)

from syncerapi.v1.core import (
    cli,
)


@cli.group(name='vmware')
def cli_vmware():
    """VMware commands"""

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
    except Exception:
        if debug:
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
    except Exception:
        if debug:
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
