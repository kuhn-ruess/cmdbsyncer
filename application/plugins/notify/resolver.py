"""
Notification Hub — rule evaluator and dispatch pipeline.

Given an event dict (source, event_type, context), produce a list of
(contact, channel) pairs and fire each one.

Design choices:

- Rules fire in ascending `sort_field` order; every match contributes
  to the recipient set unless the rule has `last_match=True`.
- Vacations are applied AFTER recipient expansion so a substitute
  gets the alert instead.
- Shift calendars act as an intersection filter on group membership:
  if a rule names a calendar, only group members who are also listed
  on the currently-active event in that calendar get the alert.
- LDAP-backed dynamic members of a NotifyContactGroup are materialised
  on the fly into transient (un-saved) NotifyContact objects; they
  share the same delivery path as stored contacts.
- Failures in one delivery never abort sibling deliveries — each
  (contact, channel) is tried under its own try/except and the
  outcome is logged.
"""
# pylint: disable=import-outside-toplevel,no-member,cell-var-from-loop
# pylint: disable=too-many-locals,too-many-branches,unused-argument
import logging
import re
from datetime import datetime

from application import log as log_helper

from .models import (
    NotifyContact,
    NotifyDispatchRule,
    NotifyVacation,
)

log = logging.getLogger(__name__)


# --- Helpers ---------------------------------------------------------------


def _regex_match(pattern, value):
    """`re.search` with graceful compile-failure fallback."""
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, str(value or '')))
    except re.error:
        return False


def _context_value(event, key):
    """Get a context key with case-insensitive fallback + dotted path."""
    if not key:
        return ''
    if key in event:
        return event[key]
    ctx = event.get('context') or {}
    return ctx.get(key, ctx.get(key.lower(), ''))


def _active_on_call(calendar, when):
    """Return the set of NotifyContact IDs currently on call in `calendar`.

    The shift sync populates `calendar.cached_events` as a list of
    `{start, end, summary, matched_contact_ids}` dicts; we just pick
    the ones whose window contains `when`.
    """
    if not calendar or not calendar.cached_events:
        return None  # no calendar → no intersection filter
    hot = set()
    for ev in calendar.cached_events:
        try:
            if ev['start'] <= when <= ev['end']:
                hot.update(ev.get('matched_contact_ids') or [])
        except (KeyError, TypeError):
            continue
    return hot


def _expand_group(group, when):
    """Return the list of NotifyContact objects currently in `group`.

    Combines static members, tag-based members and LDAP-resolved
    members (cached per dispatch — see `_ldap_cache` below).
    """
    seen = {}
    for contact in (group.members or []):
        if contact and contact.enabled:
            seen[str(contact.pk)] = contact
    if group.dynamic_tag:
        for contact in NotifyContact.objects(
                enabled=True, tags=group.dynamic_tag):
            seen[str(contact.pk)] = contact
    if group.ldap_account and group.ldap_filter:
        for contact in _ldap_expand(
                group.ldap_account, group.ldap_filter):
            seen[str(contact.pk or contact.name)] = contact
    return list(seen.values())


# --- LDAP expansion -------------------------------------------------------


def _ldap_expand(account_name, search_filter):
    """Best-effort: return transient NotifyContact objects from LDAP.

    The LDAP host-import plugin already has connection + filter
    machinery. We reuse it narrowly: account config + search_filter
    + attributes we care about (mail, telephoneNumber, cn).
    """
    try:
        # pylint: disable=import-outside-toplevel
        from application.plugins.ldap.ldap import _connect  # noqa: F401
        from application.helpers.get_account import get_account_by_name
        import ldap
        from ldap.controls.libldap import SimplePagedResultsControl
    except ImportError:
        log.warning('LDAP plugin not available — skipping dynamic LDAP group')
        return []
    try:
        config = get_account_by_name(account_name)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('LDAP account %r not found: %s', account_name, exp)
        return []
    config = dict(config)
    config['debug'] = False
    conn = _connect(config)
    if conn is None:
        return []
    base_dn = config.get('base_dn') or ''
    attributes = ['mail', 'telephoneNumber', 'cn']
    page = SimplePagedResultsControl(True, size=200, cookie='')
    contacts = []
    try:
        resp = conn.search_ext(base_dn, ldap.SCOPE_SUBTREE, search_filter,
                               attributes, serverctrls=[page])
        _r, rdata, _m, _c = conn.result3(resp)
        for dn, entry in rdata:
            if not isinstance(entry, dict):
                continue
            def _first(attr):
                vals = entry.get(attr) or []
                return vals[0].decode('utf-8', 'replace') if vals else None
            name = _first('cn') or dn
            contact = NotifyContact(
                name=name,
                email=_first('mail'),
                phone=_first('telephoneNumber'),
                source='ldap',
                enabled=True,
            )
            contact.pk = None  # transient
            contacts.append(contact)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('LDAP dynamic expansion failed for %s: %s',
                    account_name, exp)
        return []
    return contacts


# --- Vacation filter ------------------------------------------------------


def _vacation_substitute(contact, when):
    """If `contact` is on vacation at `when`, return the substitute
    or None to drop. Otherwise return the contact itself."""
    if not contact or not getattr(contact, 'pk', None):
        return contact  # transient (LDAP) contacts bypass vacation
    hits = NotifyVacation.objects(contact=contact,
                                  from_date__lte=when,
                                  to_date__gte=when)
    for vac in hits:
        return vac.substitute  # may be None → drop
    return contact


# --- Main entry point -----------------------------------------------------


def resolve_and_dispatch(event, when=None, dry_run=False):
    """
    Walk every matching NotifyDispatchRule, expand to contacts, apply
    shift/vacation filters, and fire the deliveries. Returns a list of
    (contact_name, channel_name, outcome, error) tuples.

    `event` shape:
        {
            'source':     'checkmk' | 'netbox' | 'generic' | ...,
            'event_type': 'host.down' | 'service.problem' | ...,
            'host':       'web01.example.com',
            'service':    'CPU Load',
            'state':      'CRIT',
            'title':      '...',         # optional, for humans
            'message':    '...',         # optional, body
            'context':    { arbitrary k/v from the source },
        }

    `dry_run=True` resolves recipients and channels but doesn't send.
    """
    when = when or datetime.utcnow()
    outcomes = []
    fired_rules = 0

    rules = list(NotifyDispatchRule.objects(enabled=True).order_by('sort_field'))
    for rule in rules:
        if rule.source_match and rule.source_match != event.get('source'):
            continue
        if not _regex_match(rule.event_type_match, event.get('event_type')):
            continue
        if rule.context_key:
            if not _regex_match(rule.context_value_match,
                                _context_value(event, rule.context_key)):
                continue

        fired_rules += 1
        on_call_filter = _active_on_call(rule.shift_calendar, when)

        recipients = {}  # key → contact
        for group in (rule.target_groups or []):
            if not group or not group.enabled:
                continue
            for contact in _expand_group(group, when):
                if (on_call_filter is not None
                        and str(getattr(contact, 'pk', '') or '') not in on_call_filter):
                    continue
                resolved = _vacation_substitute(contact, when)
                if resolved is None:
                    continue
                key = (getattr(resolved, 'pk', None)
                       or resolved.email or resolved.name)
                recipients[str(key)] = resolved

        channels = list(rule.channels or [])
        for contact in recipients.values():
            effective_channels = channels or (contact.default_channels or [])
            for channel in effective_channels:
                if dry_run:
                    outcomes.append(
                        (contact.name, channel.name, 'dry-run', None))
                    continue
                err = _send(channel, contact, event)
                outcomes.append(
                    (contact.name, channel.name,
                     'ok' if err is None else 'failed', err))

        if rule.last_match:
            break

    log_helper.log(
        f'Notify dispatch: {fired_rules} rule(s) matched, '
        f'{len(outcomes)} delivery(ies)',
        source='notify',
        details=[('event_type', event.get('event_type')),
                 ('host', event.get('host'))],
    )
    return outcomes


def _send(channel, contact, event):
    """
    Deliver one event to one contact via one channel. Reuses the
    Enterprise `NotificationChannel` dispatcher when the feature is
    active; falls back to stdout-logging so OSS installs still see
    *something* happen.
    """
    payload = {
        'title': event.get('title') or (event.get('event_type') or 'Event'),
        'message': event.get('message') or '',
        'severity': event.get('state', 'info').lower(),
        'source': event.get('source') or 'notify',
        'event_type': event.get('event_type'),
        'target': event.get('host'),
        'outcome': event.get('outcome'),
        'details': {
            'contact': contact.name,
            'contact_email': contact.email or '',
            'contact_phone': contact.phone or '',
            **{k: v for k, v in (event.get('context') or {}).items()
               if isinstance(v, (str, int, float, bool))},
        },
    }
    # Email is handled natively so OSS installs can deliver without
    # the Enterprise notifications feature. Non-email types try the
    # Enterprise channel adapters when available, otherwise fall
    # back to an email-to-contact as a best-effort.
    if channel.type == 'email':
        return _smtp_send(channel, contact, payload)
    try:
        # pylint: disable=import-outside-toplevel
        from cmdbsyncer_enterprise.notifications.channels import (  # noqa: PLC0415
            slack as _slack, msteams as _teams, webhook as _wh,
        )
        dispatcher = {
            'slack':   _slack.send,
            'msteams': _teams.send,
            'webhook': _wh.send,
        }.get(channel.type)
        if not dispatcher:
            return f'unknown channel type {channel.type!r}'
        dispatcher(channel, payload)
        return None
    except ImportError:
        # Enterprise `notifications` feature not active — fall back
        # to email so OSS installs still deliver something useful.
        return _smtp_send(channel, contact, payload)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('Channel %r delivery to %s failed: %s',
                    channel.name, contact.name, exp)
        return str(exp)


def _smtp_send(channel, contact, payload):
    """Deliver `payload` to `contact` via Flask-Mail.

    Recipient selection: the channel's `email_recipients` override
    (comma-separated) wins when set, otherwise the contact's own
    `email` field. Subject gets the channel's `email_subject_prefix`
    if configured.
    """
    recipients = []
    override = (getattr(channel, 'email_recipients', '') or '').strip()
    if override:
        recipients = [r.strip() for r in override.split(',') if r.strip()]
    elif contact and contact.email:
        recipients = [contact.email]

    if not recipients:
        return 'no email recipients (contact has no email, no channel override)'

    try:
        from flask_mail import Mail, Message  # noqa: PLC0415
        from flask import current_app  # noqa: PLC0415
    except ImportError:
        return 'flask_mail not installed — install the OSS email extras'

    try:
        mail_ext = current_app.extensions.get('mail')
        mail = mail_ext or Mail(current_app)
        prefix = (getattr(channel, 'email_subject_prefix', '') or '').strip()
        subject = payload.get('title') or (
            payload.get('event_type') or 'Notification')
        if prefix:
            subject = f'{prefix} {subject}'
        body_lines = [payload.get('message') or '']
        details = payload.get('details') or {}
        if details:
            body_lines.append('')
            for key, value in details.items():
                body_lines.append(f'{key}: {value}')
        msg = Message(
            subject=subject,
            recipients=recipients,
            body='\n'.join(body_lines).strip() or subject,
        )
        mail.send(msg)
        return None
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('SMTP delivery for %r to %s failed: %s',
                    getattr(channel, 'name', 'email'), recipients, exp)
        return f'smtp: {exp}'


def _clone_with(channel, **overrides):
    """Shallow-clone a NotificationChannel with a field swapped — keeps
    the original document untouched so rule deliveries don't pollute
    the Channel's stored recipient list."""
    class _ChannelClone:  # pylint: disable=too-few-public-methods
        pass
    clone = _ChannelClone()
    for field in ('name', 'type', 'webhook_url', 'webhook_secret_env',
                  'slack_channel', 'slack_mention', 'email_recipients',
                  'email_subject_prefix', 'extra_headers'):
        setattr(clone, field, getattr(channel, field, None))
    for key, value in overrides.items():
        setattr(clone, key, value)
    return clone
