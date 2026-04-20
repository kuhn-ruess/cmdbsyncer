"""
Rule Manger
"""
import click
from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .rule_import_export import import_rules, export_rules, export_all_rules
from .autorules import create_rules

cli_rules = register_cli_group(app, 'rules', 'rules', "Syner Rules import and Export")

@cli_rules.command('export_rules')
@click.argument("rule_type", default="")
def cli_export_rules(rule_type):
    """
    Export Rules by Category
    """
    export_rules(rule_type)

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
def cli_import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer
    """
    import_rules(rulefile_path)

@cli_rules.command('export_all_rules')
@click.argument("target_path", default="")
@click.option("--include-hosts", is_flag=True, default=False,
              help="Also export hosts/objects from the Host collection "
                   "(skipped by default).")
@click.option("--include-accounts", is_flag=True, default=False,
              help="Also export accounts (skipped by default).")
@click.option("--include-users", is_flag=True, default=False,
              help="Also export user accounts including hashed passwords "
                   "and roles (skipped by default — treat the output as secret).")
def cli_export_all_rules(target_path, include_hosts, include_accounts, include_users):
    """
    Export all Rules of every type into a single file.
    If no path is given, a timestamped filename is generated.
    """
    export_all_rules(
        target_path or None,
        include_hosts=include_hosts,
        include_accounts=include_accounts,
        include_users=include_users,
    )

@cli_rules.command('create_rules')
@click.option("--debug", default=False, is_flag=True)
def cli_create_rules(debug):
    """
    Create Syncer Rules based on Config
    """
    create_rules(None, debug)

register_cronjob('Syncer: Autocreate Rules', create_rules)
