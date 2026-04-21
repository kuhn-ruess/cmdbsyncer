#!/usr/bin/env python3
"""Import JDISC Data"""
import click

from application import app, logger
from application.helpers.plugins import register_cli_group

from syncerapi.v1 import (
    register_cronjob,
)

from .devices import JdiscDevices
from .applications import JdiscApplications
from .executables import JdiscExecutables

cli_jdisc = register_cli_group(app, 'jdisc', 'jdisc', "JDisc commands")


def _run_job(job_label, account, debug, runner):
    """Execute a JDisc job, logging and re-raising failures.

    Cron runs used to swallow any Exception (except in debug mode), so
    a broken JDisc job looked successful while doing nothing. We now
    log the exception and always re-raise so cron records a failure
    and the CLI exits non-zero.
    """
    try:
        runner()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.exception("%s failed for account %s: %s", job_label, account, error)
        if not debug:
            print(f"{job_label} failed for {account}: {error}")
        raise


#   .-- Devices
def jdisc_device_import(account, debug=False):
    """
    Jdisc Device Import
    """
    def _run():
        jdisc = JdiscDevices(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_device_import"
        jdisc.import_devices()
    _run_job("JDisc device import", account, debug, _run)


def jdisc_device_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    def _run():
        jdisc = JdiscDevices(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_device_inventorize"
        jdisc.inventorize()
    _run_job("JDisc device inventorize", account, debug, _run)


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
    def _run():
        jdisc = JdiscApplications(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_applications_import"
        jdisc.import_applications()
    _run_job("JDisc applications import", account, debug, _run)


def jdisc_application_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    def _run():
        jdisc = JdiscApplications(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_application_inventorize"
        jdisc.inventorize()
    _run_job("JDisc applications inventorize", account, debug, _run)


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
    def _run():
        jdisc = JdiscExecutables(account)
        jdisc.name = f"Import data from {account}"
        jdisc.source = "jdisc_executables_import"
        jdisc.import_executables()
    _run_job("JDisc executables import", account, debug, _run)


def jdisc_executables_inventorize(account, debug=False):
    """
    JDISC Inner Inventorize
    """
    def _run():
        jdisc = JdiscExecutables(account)
        jdisc.name = f"Inventorize data from {account}"
        jdisc.source = "jdisc_executables_inventorize"
        jdisc.inventorize()
    _run_job("JDisc executables inventorize", account, debug, _run)


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
