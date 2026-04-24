"""
iCal shift-calendar sync.

Pulls the HTTPS feed behind every `NotifyShiftCalendar`, parses the
VEVENT entries, and caches them on the document as a list of
`{start, end, summary, matched_contact_ids}` dicts for the resolver.

Contact matching is by name — any NotifyContact whose `name` appears
as a whole-word substring of an event's summary or description is
treated as on-call during that event's window. Keeps calendars
portable: you can use Google/Outlook/CalDAV without teaching them
about Syncer IDs.
"""
import logging
import re
from datetime import datetime, timezone

import requests

from application.helpers.get_account import (
    get_account_by_name, AccountNotFoundError,
)

from .models import NotifyContact, NotifyShiftCalendar

log = logging.getLogger(__name__)


def _parse_ics_dt(value):
    """Parse an iCal DATE or DATE-TIME value.

    Supports the shapes actually used by Google/Outlook/CalDAV:
      20261030T140000Z, 20261030T140000, 20261030, plus ;TZID=... variants
    already trimmed to just the value part by the caller.
    """
    value = (value or '').strip()
    if not value:
        return None
    if len(value) == 8:  # YYYYMMDD
        return datetime.strptime(value, '%Y%m%d').replace(tzinfo=timezone.utc)
    if value.endswith('Z'):
        return datetime.strptime(value[:-1], '%Y%m%dT%H%M%S').replace(
            tzinfo=timezone.utc)
    try:
        return datetime.strptime(value, '%Y%m%dT%H%M%S').replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_vevents(ics_text):
    """Yield `{start, end, summary, description}` per VEVENT.

    Minimal parser — handles BEGIN/END:VEVENT blocks, DTSTART / DTEND
    (with or without TZID parameter), SUMMARY and DESCRIPTION. Line
    continuations (lines starting with a space) are folded per RFC 5545.
    """
    # RFC 5545 line unfolding.
    raw = ics_text.replace('\r\n', '\n')
    unfolded = re.sub(r'\n[ \t]', '', raw)

    block = None
    for line in unfolded.split('\n'):
        if line.startswith('BEGIN:VEVENT'):
            block = {}
            continue
        if line.startswith('END:VEVENT'):
            if block:
                yield block
            block = None
            continue
        if block is None or ':' not in line:
            continue
        name, value = line.split(':', 1)
        key = name.split(';', 1)[0].upper()
        if key == 'DTSTART':
            block['start'] = _parse_ics_dt(value)
        elif key == 'DTEND':
            block['end'] = _parse_ics_dt(value)
        elif key == 'SUMMARY':
            block['summary'] = value
        elif key == 'DESCRIPTION':
            block['description'] = value.replace('\\n', '\n')


def _match_contacts(summary, description):
    """Return a list of NotifyContact IDs whose `name` appears in the
    summary / description as a whole-word substring (case-insensitive).
    """
    haystack = f'{summary or ""}\n{description or ""}'.lower()
    matched = []
    for contact in NotifyContact.objects(enabled=True).only('pk', 'name'):
        needle = (contact.name or '').strip().lower()
        if not needle:
            continue
        if re.search(rf'(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])',
                     haystack):
            matched.append(str(contact.pk))
    return matched


def sync_calendar(calendar):
    """Fetch and cache the iCal feed for one `NotifyShiftCalendar`.

    Stores an error message on `last_sync_error` on failure but never
    raises to the caller — a single bad feed shouldn't kill the cron.
    """
    auth = None
    if calendar.auth_account:
        # Passwords always come from Accounts (authoritative credential
        # store), never from env vars — rotation then goes through the
        # normal Accounts UI + audit log.
        try:
            account = get_account_by_name(calendar.auth_account)
            username = account.get('username') or ''
            password = account.get('password') or ''
            if username and password:
                auth = (username, password)
        except AccountNotFoundError:
            log.warning(
                "iCal auth account %r for calendar %r not found",
                calendar.auth_account, calendar.name,
            )
    try:
        resp = requests.get(calendar.ical_url, timeout=30, auth=auth)
        resp.raise_for_status()
        events = []
        for block in _parse_vevents(resp.text):
            start = block.get('start')
            end = block.get('end')
            if not start or not end:
                continue
            events.append({
                'start': start,
                'end': end,
                'summary': block.get('summary') or '',
                'matched_contact_ids': _match_contacts(
                    block.get('summary'), block.get('description')),
            })
        calendar.cached_events = events
        calendar.last_sync_at = datetime.utcnow()
        calendar.last_sync_error = None
        calendar.save()
        return len(events)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('Shift calendar %r sync failed: %s', calendar.name, exp)
        calendar.last_sync_error = str(exp)
        calendar.last_sync_at = datetime.utcnow()
        calendar.save()
        return 0


def sync_all():
    """Refresh every enabled calendar. Returns (ok, failed)."""
    ok, failed = 0, 0
    for cal in NotifyShiftCalendar.objects(enabled=True):
        sync_calendar(cal)
        if cal.last_sync_error:
            failed += 1
        else:
            ok += 1
    return ok, failed
