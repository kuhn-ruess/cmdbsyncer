"""
Notification Hub CLI + REST + cron registration.

The main business logic lives in `resolver.py` (rule evaluation +
dispatch) and `ical.py` (shift-calendar sync). This module is the
Flask/CLI plumbing.
"""
# pylint: disable=import-outside-toplevel,too-many-arguments
# pylint: disable=too-many-positional-arguments,wrong-import-position
# pylint: disable=wrong-import-order
import click

from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group
from application.modules.debug import ColorCodes
from application import app  # noqa: F401  needed for the CLI group registration

from .models import (  # noqa: F401  imported for MongoEngine registration
    NotifyContact,
    NotifyContactGroup,
    NotifyVacation,
    NotifyShiftCalendar,
    NotifyDispatchRule,
)
from .queue import enqueue as _enqueue_job
from .resolver import resolve_and_dispatch
from .ical import sync_all as sync_all_calendars


_cli_notify = register_cli_group(app, 'notify', 'notify',
                                 "Notification Hub dispatch + calendar sync")


#   .-- CLI: sync_calendars ------------------------------------------
@_cli_notify.command('sync_calendars')
def cli_sync_calendars():
    """Refresh every enabled iCal feed into the cached_events table."""
    ok, failed = sync_all_calendars()
    print(f"{ColorCodes.OKGREEN}Synced{ColorCodes.ENDC}: "
          f"{ok} ok, {failed} failed")


def _sync_calendars_cron(_account=None):
    """Cron job entry point. Cron groups pass the account name or nothing."""
    sync_all_calendars()


register_cronjob("Notify: Sync Shift Calendars", _sync_calendars_cron)


#   .-- CLI: test_dispatch -------------------------------------------
@_cli_notify.command('test_dispatch')
@click.option('--event-type', default='host.down',
              help='Event type identifier (regex-matched by rules).')
@click.option('--source', default='checkmk',
              help='Event source identifier.')
@click.option('--host', default='demo-host', help='Host name.')
@click.option('--service', default='', help='Service name.')
@click.option('--state', default='CRIT', help='State label (CRIT/WARN/OK).')
@click.option('--dry-run/--send', default=True,
              help='Resolve recipients without delivering.')
def cli_test_dispatch(event_type, source, host, service, state, dry_run):
    """Resolve an event against the dispatch rules and print the result."""
    event = {
        'source': source,
        'event_type': event_type,
        'host': host,
        'service': service,
        'state': state,
        'title': f'[{state}] {host} {service}'.strip(),
        'message': f'Test dispatch for {event_type}',
        'context': {},
    }
    outcomes = resolve_and_dispatch(event, dry_run=dry_run)
    if not outcomes:
        print(f"{ColorCodes.WARNING}No recipients resolved"
              f"{ColorCodes.ENDC}")
        return
    for contact_name, channel_name, outcome, err in outcomes:
        color = {
            'ok': ColorCodes.OKGREEN,
            'dry-run': ColorCodes.OKBLUE,
            'failed': ColorCodes.FAIL,
        }.get(outcome, ColorCodes.ENDC)
        err_str = f' — {err}' if err else ''
        print(f"  {color}{outcome:<8}{ColorCodes.ENDC} "
              f"{contact_name:<30} via {channel_name}{err_str}")


#   .-- REST endpoints -----------------------------------------------
# Registered as a Flask-RESTX Namespace on the shared API object —
# same pattern every other plugin uses (ansible, snow_api, …). That
# gives us:
#   - automatic Swagger docs at /api/v1/
#   - CSRF exemption (blanket-set for the api blueprint)
#   - per-IP auth rate limiting shared with the rest of the API
# Endpoints:
#   POST /api/v1/notify/dispatch
#   GET  /api/v1/notify/dispatch/<job_id>
from syncerapi.v1.rest import API  # noqa: E402
from .rest_api.notify import API as _notify_ns  # noqa: E402

API.add_namespace(_notify_ns, path='/notify')
