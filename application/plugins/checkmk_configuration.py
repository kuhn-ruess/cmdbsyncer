"""
Add Configuration in Checkmk
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member, too-many-locals
import click
from application.modules.checkmk.cmk2 import cli_cmk
from application.helpers.cron import register_cronjob
from application.modules.checkmk.inits import (
    export_bi_rules,
    export_bi_aggregations,
    export_rules,
    export_groups,
    activate_changes,
    bake_and_sign_agents,
    inventorize_hosts,
    show_missing,
    export_users,
    export_tags,
    export_downtimes,
    export_dcd_rules,
    export_passwords,
)


#   .-- Command: Export Downtimes
@cli_cmk.command('export_downtimes')
@click.argument('account')
#pylint: disable=too-many-locals
def cli_export_downtimes(account):
    """
    Export Dowtimes to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_downtimes SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    export_downtimes(account)



#.
#   .-- Command: Export Tags
@cli_cmk.command('export_tags')
@click.argument('account')
@click.option("--dry-run", default=False, is_flag=True)
@click.option("--save-requests", default='')
#pylint: disable=too-many-locals
def cli_export_tags(account, dry_run, save_requests):
    """
    Export Hosttags Groups to Checkmk

    ### Example
    _./cmdbsyncer checkmk show_missing_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    export_tags(account, dry_run, save_requests)

#.

#   .-- Command: Show Hosts not in Syncer
@cli_cmk.command('show_missing_hosts')
@click.argument('account')
#pylint: disable=too-many-locals
def cli_missing_hosts(account):
    """
    Check which Hosts are in Checkmk but not in Syncer

    ### Example
    _./cmdbsyncer checkmk show_missing_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    show_missing(account)
#.

#   .-- Command: Export Rulesets

@cli_cmk.command('export_rules')
@click.argument("account")
def cli_export_rules(account):
    """
    Export all configured Rules to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_rules(account)

#.
#   .-- Command: Export Group
@cli_cmk.command('export_groups')
@click.argument("account")
@click.option('-t', '--test-run', is_flag=True)
#pylint: disable=too-many-locals, too-many-branches
def cli_export_groups(account, test_run):
    """
    Create Groups in Checkmk

    ### Example
    _./cmdbsyncer checkmk export_groups SITEACCOUNT_


    Args:
        account (string): Name Account Config
        test_run (bool): Only Print Result ( default is False )
    """
    export_groups(account, test_run)


#.
#   .-- Command: Activate Changes
@cli_cmk.command('activate_changes')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def cli_activate_changes(account):
    """
    Activate Changes in given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk activate_changes SITEACCOUNT_


    Args:
        account (string): Name CHeckmk Account Config
    """
    activate_changes(account)



#.
#   .-- Command: Bake and Sign agents
@cli_cmk.command('bake_and_sign_agents')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def cli_bake_and_sign_agents(account):
    """
    Bake and Sign Agents for given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk bake_and_sign_agents SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    bake_and_sign_agents(account)

#.
#   .-- Command: Host Inventory

@cli_cmk.command('inventorize_hosts')
@click.argument('account')
#pylint: disable=too-many-locals
def cli_inventorize_hosts(account):
    """
    Do an Status Data inventory on given Checkmk Instance.
    Requires CMK Version greater then 2.1p9

    ### Example
    _./cmdbsyncer checkmk inventorize_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    inventorize_hosts(account)
#.
#   .-- Command: Checkmk BI

@cli_cmk.command('export_bi_rules')
@click.argument("account")
def cli_export_bi_rules(account):
    """
    Export all BI Rules to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_bi_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_bi_rules(account)

@cli_cmk.command('export_bi_aggregations')
@click.argument("account")
def cli_export_bi_aggregations(account):
    """
    Export all BI Aggregations to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_bi_aggregations SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_bi_aggregations(account)
#.

@cli_cmk.command('export_users')
@click.argument("account")
def cli_cmk_users(account):
    """
    Export configured Users and their settings to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_users SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_users(account)

@cli_cmk.command('export_dcd_rules')
@click.argument("account")
def cli_cmk_dcd(account):
    """
    Export Rules for DCD Deamon

    ### Example
    _./cmdbsyncer checkmk export_dcd_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_dcd_rules(account)

@cli_cmk.command('export_passwords')
@click.argument("account")
def cli_cmk_passwords(account):
    """
    Export Rules for Password Export

    ### Example
    _./cmdbsyncer checkmk export_passwords SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_passwords(account)


register_cronjob('Checkmk: Export Rules', export_rules)
register_cronjob('Checkmk: Export Groups', export_groups)
register_cronjob('Checkmk: Export BI Rules', export_bi_rules)
register_cronjob('Checkmk: Export BI Aggregations', export_bi_aggregations)
register_cronjob('Checkmk: Inventorize', inventorize_hosts)
register_cronjob('Checkmk: Activate Changes', activate_changes)
register_cronjob('Checkmk: Bake and Sign Agents', bake_and_sign_agents)
register_cronjob('Checkmk: Export Users', export_users)
register_cronjob('Checkmk: Export Tags', export_tags)
register_cronjob('Checkmk: Export Downtimes', export_downtimes)
register_cronjob('Checkmk: Export DCD Rules', export_dcd_rules)
register_cronjob('Checkmk: Export Passwords', export_passwords)
