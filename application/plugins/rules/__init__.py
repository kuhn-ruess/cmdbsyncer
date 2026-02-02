"""
Rule Manger
"""
from application import app
import click

from .rule_import_export import import_rules, export_rules


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
