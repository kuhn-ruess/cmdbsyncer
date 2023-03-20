"""
Add Configuration in Checkmk
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member, too-many-locals
import click
from application.modules.checkmk.cmk2 import cli_cmk
from application.helpers.cron import register_cronjob
from application.modules.checkmk.inits import (
    export_bi_rules,
    export_rules,
    export_groups,
    activate_changes,
    bake_and_sign_agents,
    inventorize_hosts,
)




#   .-- Command: Export Rulesets

@cli_cmk.command('export_rules')
@click.argument("account")
def cli_export_rules(account):
    """
    Export all configured Rules to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_rules SITEACCOUNT_


    Args:
        account (string): Name Account Config
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
    ## Create Groups in Checkmk

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
    ## Activate Changes in given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk activate_changes SITEACCOUNT_


    Args:
        account (string): Name Account Config
    """
    activate_changes(account)



#.
#   .-- Command: Bake and Sign agents
@cli_cmk.command('bake_and_sign_agents')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def cli_bake_and_sign_agents(account):
    """
    ## Bake and Sign Agents for given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk bake_and_sign_agents SITEACCOUNT_


    Args:
        account (string): Name Account Config
    """
    bake_and_sign_agents(account)

#.
#   .-- Command: Host Inventory

@cli_cmk.command('inventorize_hosts')
@click.argument('account')
#pylint: disable=too-many-locals
def cli_inventorize_hosts(account):
    """
    ## Do an Status Data inventory on given Checkmk Instance.
    Requires CMK Version greater then 2.1p9

    ### Example
    _./cmdbsyncer checkmk inventorize_hosts SITEACCOUNT_

    Args:
        account (string): Name Account Config
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
        account (string): Name Account Config
    """
    export_bi_rules(account)

#.

register_cronjob('Checkmk: Export Rules', export_rules)
register_cronjob('Checkmk: Export Groups', export_groups)
register_cronjob('Checkmk: Export BI Rules', export_bi_rules)
register_cronjob('Checkmk: Inventory', inventorize_hosts)
register_cronjob('Checkmk: Activate Changes', activate_changes)
register_cronjob('Checkmk: Bake and Sign Agents', bake_and_sign_agents)
