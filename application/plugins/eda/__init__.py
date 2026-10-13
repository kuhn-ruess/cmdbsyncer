"""
Event Driven Ansible: send rule based events to an EDA event stream
"""
import json

import click

from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group
from application.models.host import Host
from application.modules.debug import ColorCodes as CC

from .sender import EdaSender, build_payload

cli_eda = register_cli_group(app, 'eda', 'eda', "Event Driven Ansible")


#   .-- Command: send events
def send_events(account, dry_run=False, debug=False):
    """
    Evaluate the EDA rules for every host and post their events to the
    event stream of the account
    """
    sender = EdaSender(account)
    sender.dry_run = dry_run
    sender.debug = debug
    try:
        counts = sender.send_events()
    except Exception as error:  # pylint: disable=broad-except
        sender.record_exception(error)
        raise
    print(f"{CC.OKGREEN}Sent {counts['sent']}, failed {counts['failed']}, "
          f"skipped as recently sent {counts['skipped']}{CC.ENDC}")


@cli_eda.command('send_events')
@click.argument('account')
@click.option('--dry-run', is_flag=True, default=False,
              help='Only print the events, send and record nothing.')
@click.option('--debug', is_flag=True, default=False)
def cli_send_events(account, dry_run, debug):
    """
    Send the events of the EDA rules to the event stream of ACCOUNT
    """
    send_events(account, dry_run=dry_run, debug=debug)
#.


#   .-- Command: debug host
@cli_eda.command('debug_host')
@click.argument('hostname')
@click.option('--debug', is_flag=True, default=False)
def cli_debug_host(hostname, debug):  # pylint: disable=unused-argument
    """
    Show which EDA rules match HOSTNAME and the events it would send
    """
    db_host = Host.objects(hostname=hostname).first()
    if not db_host:
        print(f"{CC.FAIL}Host not found{CC.ENDC}")
        return
    sender = EdaSender(False)
    sender.actions.debug = True
    events = sender.host_events(db_host)
    if not events:
        print(f"{CC.WARNING}No events for this host{CC.ENDC}")
    for event in events:
        if event['error']:
            print(f"{CC.FAIL}{event['rule_name']}: {event['error']}{CC.ENDC}")
            continue
        print(json.dumps(build_payload(hostname, event), indent=2))
#.


register_cronjob('EDA: Send Events', send_events)
