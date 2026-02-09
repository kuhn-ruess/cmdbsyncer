"""
Rule Manger
"""
from application import app
from application.helpers.cron import register_cronjob
import click

from .rule_import_export import import_rules, export_rules
from .autorules import create_rules


@app.cli.group(name='rules')
def cli_rules():
    """Syner Rules import and Export"""

@cli_rules.command('export_rules')
@click.argument("rule_type", default="")
def export_rules(rule_type):
    """
    Export Rules by Category
    """
    export_rules(rule_type)

@cli_rules.command('import_rules')
@click.argument("rulefile_path")
def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer
    """
    import_rules(rulefile_path)

@cli_rules.command('create_rules')
@click.option("--debug", default=False, is_flag=True)
def import_rules(debug):
    """
    Create Syncer Rules based on Config
    """
    create_rules(None, debug)

register_cronjob('Syncer: Autocreate Rules', create_rules)