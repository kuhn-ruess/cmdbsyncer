"""
Notification dispatcher.

Two event sources feed it:

    `dispatch_log_entry(message, source, has_error, details, hosts)`
        — called from `Log._log_function` after each entry is saved.
        Each log entry produces one notification. CLI wrappers and
        `Plugin.save_log()` are expected to consolidate so a single
        command run only emits one canonical log entry.

        We hook the Log helper directly instead of installing a
        Python ``logging.Handler`` because the OSS 'debug' logger
        level is configurable and routinely high enough to drop
        records before any handler sees them — the entry would land
        in the Log view but no notification would fire.

    `dispatch_audit_event(entry)` — called from the audit recorder
        when an ``AuditEntry`` is persisted.

All matching enabled rules fire, in ``priority`` order. A rule's
optional ``match_pattern`` is a regex against the log message (log)
or audit ``event_type`` (audit). ``only_errors`` (log only) limits
to entries flagged as errors. Cooldown is per rule + dedup-key.

Dispatch runs in a background worker so slow Slack/SMTP endpoints
don't back-pressure the caller. An ``atexit`` hook drains the queue
before the interpreter exits — without it, CLI invocations would lose
notifications because the daemon worker dies mid-send.

A thread-local guard prevents the dispatch path from re-entering the
dispatcher when a channel sender writes its own log entry (e.g.
"email sent to …" / "channel send failed: …").
"""
import atexit
import logging
import queue
import re
import threading
import time
from datetime import datetime, timedelta

from jinja2 import Environment, BaseLoader, select_autoescape
from mongoengine.errors import DoesNotExist, NotUniqueError

from application.helpers import notification_channels
from application.models.notification_channel import NotificationChannel
from application.models.notification_rule import NotificationRule
from application.models.notification_state import NotificationState

log = logging.getLogger(__name__)

# How long the atexit drain waits for the worker to finish pending
# deliveries before giving up. Long enough for SMTP / Slack round-trips,
# short enough not to make the CLI hang on a misconfigured channel.
EXIT_DRAIN_TIMEOUT_SECONDS = 30

_jinja = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(disabled_extensions=('txt', 'md')),
    trim_blocks=True, lstrip_blocks=True,
)

_queue = queue.Queue(maxsize=1000)
_worker_started = threading.Lock()
_worker_running = False  # pylint: disable=invalid-name

# Set on the worker thread while it is executing a dispatch. Channel
# senders that emit their own log.log() entry must not loop back into
# the dispatcher.
_in_dispatch = threading.local()


def _is_dispatching():
    return getattr(_in_dispatch, 'active', False)


def _start_worker():
    global _worker_running  # pylint: disable=global-statement
    with _worker_started:
        if _worker_running:
            return
        thread = threading.Thread(
            target=_worker_loop, name='notification-dispatcher', daemon=True,
        )
        thread.start()
        _worker_running = True


def _worker_loop():
    while True:
        source_type, event = _queue.get()
        _in_dispatch.active = True
        try:
            _dispatch(source_type, event)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Notification dispatch failed (%s)", source_type)
        finally:
            _in_dispatch.active = False
            _queue.task_done()


def _pattern_matches(pattern, value):
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, str(value or '')))
    except re.error:
        log.warning("Invalid regex in notification rule: %r", pattern)
        return False


def _select_rules(source_type, event):
    matching = []
    for rule in NotificationRule.objects(source_type=source_type,
                                         enabled=True).order_by('priority'):
        if source_type == 'log':
            if rule.only_errors and not event.get('has_error'):
                continue
            if not _pattern_matches(rule.match_pattern, event['message']):
                continue
        else:
            if not _pattern_matches(rule.match_pattern, event['event_type']):
                continue
        matching.append(rule)
    return matching


def _render(template, event):
    if not template:
        return None
    try:
        return _jinja.from_string(template).render(**event)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning("Jinja render failed: %s", exp)
        return None


def _allow_send(rule, dedup_key):
    now = datetime.utcnow()
    try:
        state = NotificationState.objects.get(dedup_key=dedup_key)
    except DoesNotExist:
        state = NotificationState(dedup_key=dedup_key)

    if state.last_sent_at:
        cooldown = timedelta(minutes=int(rule.cooldown_minutes or 0))
        if now - state.last_sent_at < cooldown:
            state.suppressed_count = (state.suppressed_count or 0) + 1
            try:
                state.save()
            except NotUniqueError:
                pass
            return False

    state.last_sent_at = now
    try:
        state.save()
    except NotUniqueError:
        pass
    return True


def _payload(event, rule):
    payload = dict(event)
    if rule.title_template:
        payload['title'] = _render(rule.title_template, event) or payload.get('title')
    if rule.message_template:
        payload['message'] = _render(rule.message_template, event) or payload.get('message')
    return payload


def _dispatch(source_type, event):
    try:
        rules = _select_rules(source_type, event)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("Rule selection failed for %s event", source_type)
        return
    if not rules:
        return
    for rule in rules:
        dedup_key = event.get('dedup_key') or f"rule:{rule.id}"
        if not _allow_send(rule, dedup_key):
            continue
        payload = _payload(event, rule)
        for ch_ref in rule.channels:
            try:
                channel = ch_ref if isinstance(ch_ref, NotificationChannel) \
                    else NotificationChannel.objects.get(id=ch_ref.id)
            except DoesNotExist:
                continue
            if not channel.enabled:
                continue
            try:
                notification_channels.send(channel, payload)
            except Exception as exp:  # pylint: disable=broad-exception-caught
                log.warning("Channel %r send failed: %s", channel.name, exp)
                # Surface the failure in the syncer Log too. The thread-
                # local dispatch guard is still active, so this log line
                # will not loop back into the dispatcher.
                try:
                    from application import log as syncer_log  # pylint: disable=import-outside-toplevel
                    syncer_log.log(
                        f"Notification channel {channel.name!r} "
                        f"({channel.type}) send failed: {exp}",
                        source='notification',
                        details=[('error', str(exp)),
                                 ('channel', channel.name),
                                 ('channel_type', channel.type)],
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass


def _enqueue(source_type, event):
    _start_worker()
    try:
        _queue.put_nowait((source_type, event))
    except queue.Full:
        log.warning("Notification queue full, dropping %s event", source_type)


def dispatch_audit_event(entry):
    """Enqueue a persisted ``AuditEntry`` for rule matching."""
    _enqueue('audit', {
        'event_type': entry.event_type,
        'outcome': entry.outcome,
        'title': f"Audit: {entry.event_type}",
        'message': entry.message or '',
        'actor_name': entry.actor_name,
        'actor_ip': entry.actor_ip,
        'target': entry.target_name or '',
        'target_type': entry.target_type or '',
        'target_id': entry.target_id or '',
        'details': entry.metadata or {},
        'trace_id': entry.trace_id,
        'dedup_key': f"audit:{entry.event_type}:{entry.actor_name or ''}:"
                     f"{entry.target_type or ''}:{entry.target_id or ''}",
    })


def dispatch_log_entry(message, source, has_error, details, affected_hosts):
    """Called from `Log._log_function` after the LogEntry is saved."""
    if _is_dispatching():
        # A channel sender wrote a log entry while we were already
        # delivering — do not loop back into the dispatcher.
        return
    _enqueue('log', {
        'message': message,
        'source': source,
        'has_error': bool(has_error),
        'details': details or {},
        'affected_hosts': affected_hosts or [],
        'title': message,
        'dedup_key': f"log:{source}:{message}",
    })


def _drain_on_exit():
    """Block until the dispatch queue is empty or the timeout hits.

    Without this, daemon-thread workers are killed when the CLI process
    exits, and notifications enqueued by the run never leave the box.
    """
    if not _worker_running or _queue.unfinished_tasks == 0:
        return
    deadline = time.monotonic() + EXIT_DRAIN_TIMEOUT_SECONDS
    while _queue.unfinished_tasks > 0 and time.monotonic() < deadline:
        time.sleep(0.05)


atexit.register(_drain_on_exit)
