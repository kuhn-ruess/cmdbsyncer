#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation
import click

from application.modules.jdisc.devices import JdiscDevices 
from application.modules.jdisc.applications import JdiscApplications

from syncerapi.v1 import (
    register_cronjob,
)

from syncerapi.v1.core import (
    cli,
)


@cli.group(name='jdisc')
def cli_jdisc():
    """JDisc commands"""

def jdisc_device_import(account):
    """
    Jdisc Device Import
    """
    jdisc = JdiscDevices(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_device_import"
    jdisc.import_devices()


@cli_jdisc.command('import_devices')
@click.argument('account')
def cli_jdisc_device_import(account):
    """Import Devices from JDisc"""
    jdisc_device_import(account)

def jdisc_device_inventorize(account):
    """
    JDISC Inner Inventorize
    """
    jdisc = JdiscDevices(account)
    jdisc.name = f"Inventorize data from {account}"
    jdisc.source = "jdisc_device_inventorize"
    jdisc.jdisc_inventorize()

@cli_jdisc.command('inventorize_devices')
@click.argument('account')
def cli_jdisc_device_inventorize(account):
    """Inventorize Devices from JDisc"""
    jdisc_inventorize(account)


def jdisc_applications_import(account):
    """
    Jdisc Applications Import
    """
    jdisc = JdiscApplications(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_applications_import"
    jdisc.import_applications()


@cli_jdisc.command('import_applications')
@click.argument('account')
def cli_jdisc_application_import(account):
    """Import Applications from JDisc"""
    jdisc_device_import(account)



register_cronjob("JDisc: Import Devices", jdisc_device_import)
register_cronjob("JDisc: Import Applications", jdisc_applications_import)
register_cronjob("JDisc: Inventorize Devices", jdisc_device_inventorize)
