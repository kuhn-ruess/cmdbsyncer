#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation
import click

from application.modules.jdisc.devices import JdiscDevices
from application.modules.jdisc.applications import JdiscApplications
from application.modules.jdisc.executables import JdiscExecutables

from syncerapi.v1 import (
    register_cronjob,
)

from syncerapi.v1.core import (
    cli,
)


@cli.group(name='jdisc')
def cli_jdisc():
    """JDisc commands"""

#   .-- Devices
def jdisc_device_import(account):
    """
    Jdisc Device Import
    """
    jdisc = JdiscDevices(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_device_import"
    jdisc.import_devices()

def jdisc_device_inventorize(account):
    """
    JDISC Inner Inventorize
    """
    jdisc = JdiscDevices(account)
    jdisc.name = f"Inventorize data from {account}"
    jdisc.source = "jdisc_device_inventorize"
    jdisc.inventorize()

@cli_jdisc.command('import_devices')
@click.argument('account')
def cli_jdisc_device_import(account):
    """Import Devices from JDisc"""
    jdisc_device_import(account)

@cli_jdisc.command('inventorize_devices')
@click.argument('account')
def cli_jdisc_device_inventorize(account):
    """Inventorize Devices from JDisc"""
    jdisc_device_inventorize(account)


register_cronjob("JDisc: Import Devices", jdisc_device_import)
register_cronjob("JDisc: Inventorize Devices", jdisc_device_inventorize)

#.
#   .-- Applications
def jdisc_applications_import(account):
    """
    Jdisc Applications Import
    """
    jdisc = JdiscApplications(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_applications_import"
    jdisc.import_applications()

def jdisc_application_inventorize(account):
    """
    JDISC Inner Inventorize
    """
    jdisc = JdiscApplications(account)
    jdisc.name = f"Inventorize data from {account}"
    jdisc.source = "jdisc_application_inventorize"
    jdisc.inventorize()


@cli_jdisc.command('inventorize_applications')
@click.argument('account')
def cli_jdisc_application_inventorize(account):
    """Inventorize Applications from JDisc"""
    jdisc_application_inventorize(account)

@cli_jdisc.command('import_applications')
@click.argument('account')
def cli_jdisc_application_import(account):
    """Import Applications from JDisc"""
    jdisc_applications_import(account)

register_cronjob("JDisc: Inventorize Applications", jdisc_application_inventorize)
register_cronjob("JDisc: Import Applications", jdisc_applications_import)
#.
#   .-- Executables
def jdisc_executables_import(account):
    """
    Jdisc Executables Import
    """
    jdisc = JdiscExecutables(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_executables_import"
    jdisc.import_executables()

def jdisc_executables_inventorize(account):
    """
    JDISC Inner Inventorize
    """
    jdisc = JdiscExecutables(account)
    jdisc.name = f"Inventorize data from {account}"
    jdisc.source = "jdisc_executables_inventorize"
    jdisc.inventorize()


@cli_jdisc.command('inventorize_excecutables')
@click.argument('account')
def cli_jdisc_executables_inventorize(account):
    """Inventorize Executables from JDisc"""
    jdisc_executables_inventorize(account)

@cli_jdisc.command('import_executables')
@click.argument('account')
def cli_jdisc_executables_import(account):
    """Import Executables from JDisc"""
    jdisc_executables_import(account)

register_cronjob("JDisc: Inventorize Executables", jdisc_executables_inventorize)
register_cronjob("JDisc: Import Executables", jdisc_executables_import)
#.
