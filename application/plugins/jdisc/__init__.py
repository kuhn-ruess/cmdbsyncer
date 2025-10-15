#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation
import click

from .devices import JdiscDevices
from .applications import JdiscApplications
from .executables import JdiscExecutables

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
def jdisc_device_import(account, debug=False):
    """
    Jdisc Device Import
    """
    try:
        jdisc = JdiscDevices(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_device_import"
        jdisc.import_devices()
    except Exception:
        if debug:
            raise

def jdisc_device_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    try:
        jdisc = JdiscDevices(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_device_inventorize"
        jdisc.inventorize()
    except Exception:
        if debug:
            raise

@cli_jdisc.command('import_devices')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_device_import(account, debug):
    """Import Devices from JDisc"""
    jdisc_device_import(account, debug)

@cli_jdisc.command('inventorize_devices')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_device_inventorize(account, debug):
    """Inventorize Devices from JDisc"""
    jdisc_device_inventorize(account, debug)


register_cronjob("JDisc: Import Devices", jdisc_device_import)
register_cronjob("JDisc: Inventorize Devices", jdisc_device_inventorize)

#.
#   .-- Applications
def jdisc_applications_import(account, debug=False):
    """
    Jdisc Applications Import
    """
    try:
        jdisc = JdiscApplications(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_applications_import"
        jdisc.import_applications()
    except Exception:
        if debug:
            raise

def jdisc_application_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    try:
        jdisc = JdiscApplications(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_application_inventorize"
        jdisc.inventorize()
    except Exception:
        if debug:
            raise


@cli_jdisc.command('inventorize_applications')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_application_inventorize(account, debug):
    """Inventorize Applications from JDisc"""
    jdisc_application_inventorize(account, debug)

@cli_jdisc.command('import_applications')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_application_import(account, debug):
    """Import Applications from JDisc"""
    jdisc_applications_import(account, debug)

register_cronjob("JDisc: Inventorize Applications", jdisc_application_inventorize)
register_cronjob("JDisc: Import Applications", jdisc_applications_import)
#.
#   .-- Executables
def jdisc_executables_import(account, debug=False):
    """
    Jdisc Executables Import
    """
    try:
        jdisc = JdiscExecutables(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_executables_import"
        jdisc.import_executables()
    except Exception:
        if debug:
            raise

def jdisc_executables_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    try:
        jdisc = JdiscExecutables(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_executables_inventorize"
        jdisc.inventorize()
    except Exception:
        if debug:
            raise


@cli_jdisc.command('inventorize_executables')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_executables_inventorize(account, debug):
    """Inventorize Executables from JDisc"""
    jdisc_executables_inventorize(account, debug)

@cli_jdisc.command('import_executables')
@click.option("--debug", is_flag=True)
@click.argument('account')
def cli_jdisc_executables_import(account, debug):
    """Import Executables from JDisc"""
    jdisc_executables_import(account, debug)

register_cronjob("JDisc: Inventorize Executables", jdisc_executables_inventorize)
register_cronjob("JDisc: Import Executables", jdisc_executables_import)
#.
