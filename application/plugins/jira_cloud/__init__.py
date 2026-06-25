"""Jira Cloud plugin."""
import click
from mongoengine.errors import DoesNotExist

from application.plugins.jira import jira_cli
from application.models.host import Host
from application.modules.plugin import Plugin
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite

from syncerapi.v1 import (
    register_cronjob,
)

from .jira_cloud import import_jira_cloud
from .export import export_jira_cloud
from .schema_sync import sync_jira_schema
from .models import (
    JiraCloudFilterRule,
    JiraCloudRewriteAttributeRule,
    JiraExportRule,
)
from .rules import JiraExportAttributeRule

@jira_cli.command('import_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_jira(account, debug):
    """
    Import from Cloud Instance
    """
    try:
        import_jira_cloud(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


@jira_cli.command('export_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_export_jira(account, debug):
    """
    Export Hosts/Fields to a Jira Cloud Assets Instance
    """
    try:
        export_jira_cloud(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


@jira_cli.command('sync_schema')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_sync_jira_schema(account, debug):
    """
    Cache the Jira Cloud Assets schema (used by the export GUI / plugin)
    """
    try:
        sync_jira_schema(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


def get_jira_cloud_debug_data(hostname):
    """Return debug data for the HTML host debug view.

    Mirrors the Checkmk / Netbox / i-doit `get_*_debug_data` shape:
    returns `(attributes, outcomes, rule_logs)`. The export rules are
    global (not account-bound), so this runs without a Jira account and
    without touching Jira — it only shows which rules fire and what the
    export would write for this host.
    """
    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return None, None, None

    rewrite = Rewrite()
    rewrite.cache_name = 'jira_cloud_rewrite'
    rewrite.rules = (
        JiraCloudRewriteAttributeRule.objects(enabled=True).order_by('sort_field'))
    rewrite.debug = True

    host_filter = Filter()
    host_filter.cache_name = 'jira_cloud_filter'
    host_filter.rules = JiraCloudFilterRule.objects(enabled=True).order_by('sort_field')
    host_filter.debug = True

    rule_engine = JiraExportAttributeRule()
    rule_engine.rules = JiraExportRule.objects(enabled=True).order_by('sort_field')
    rule_engine.debug = True

    plugin = Plugin()
    plugin.debug = True
    plugin.filter = host_filter
    plugin.rewrite = rewrite

    # Wipe cached jira_cloud_* entries so the rules actually re-fire.
    for key in list(db_host.cache.keys()):
        if key.lower().startswith('jira_cloud'):
            del db_host.cache[key]
    db_host.save()

    attributes = plugin.get_attributes(db_host, 'jira_cloud_export')
    outcomes = {}
    if attributes:
        result = rule_engine.get_outcomes(db_host, attributes['all'])
        for type_id, fields in (result.get('fields_by_type') or {}).items():
            for field_name, value in fields.items():
                outcomes[f"type {type_id} | {field_name}"] = value

    rule_logs = {
        'filter': host_filter.debug_lines,
        'rewrite': rewrite.debug_lines,
        'actions': rule_engine.debug_lines,
    }
    return attributes, outcomes, rule_logs


register_cronjob('Jira Cloud: Import Hosts', import_jira_cloud)
register_cronjob('Jira Cloud: Export Objects', export_jira_cloud)
register_cronjob('Jira Cloud: Sync Schema', sync_jira_schema)
