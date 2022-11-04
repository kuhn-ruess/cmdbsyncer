"""
Commands to handle Checkmk Sync
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get
from pprint import pprint
import click
from application.modules.checkmk.syncer import SyncCMK2
from application.modules.checkmk.cmk2 import cli_cmk, CmkException
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes


from application.modules.rule.filter import Filter
from application.modules.checkmk.models import CheckmkFilterRule

from application.modules.rule.rewrite import Rewrite
from application.modules.checkmk.models import CheckmkRewriteLabelRule

from application.modules.checkmk.rules import CheckmkRule
from application.modules.checkmk.models import CheckmkRule as CheckmkRuleModel

from application.models.host import Host



def load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = Filter()
    attribute_filter.rules = CheckmkFilterRule.objects(enabled=True).order_by('sort_field')

    attribute_rewrite = Rewrite()
    attribute_rewrite.rules = CheckmkRewriteLabelRule.objects(enabled=True).order_by('sort_field')

    checkmk_rules = CheckmkRule()
    checkmk_rules.rules = CheckmkRuleModel.objects(enabled=True).order_by('sort_field')
    return {
        'filter': attribute_filter,
        'rewrite': attribute_rewrite,
        'actions': checkmk_rules
    }


#   .-- Command: Export Hosts
@cli_cmk.command('export_hosts')
@click.argument("account")
def cmk_host_export(account):
    """Add hosts to a CMK 2.x Installation"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = load_rules()
            syncer = SyncCMK2()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.filter = rules['filter']
            syncer.rewrite = rules['rewrite']
            syncer.actions = rules['actions']
            syncer.run()

        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Command: Host Debug
@cli_cmk.command('debug_host')
@click.argument("hostname")
def debug_cmk_rules(hostname):
    """Show Rule Engine Outcome for given Host"""
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")

    rules = load_rules()

    syncer = SyncCMK2()
    syncer.debug = True
    rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    db_host = Host.objects.get(hostname=hostname)

    attributes = syncer.get_host_attributes(db_host)

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    actions = syncer.get_host_actions(db_host, attributes['all'])

    print(f"{ColorCodes.HEADER} ***** Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Full Label List {ColorCodes.ENDC}")
    pprint(attributes['all'])
    print(f"{ColorCodes.UNDERLINE} Filtered Label List {ColorCodes.ENDC}")
    pprint(attributes['filtered'])
    print(f"{ColorCodes.UNDERLINE} Actions {ColorCodes.ENDC}")
    pprint(actions)

#.