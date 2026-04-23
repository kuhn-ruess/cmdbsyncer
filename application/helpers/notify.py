"""
Notification emitter.

Like `audit`, this is a thin community helper that forwards to the
enterprise notification dispatcher via the hook registry. The community
call is a no-op without the `notifications` license feature.

Events that are worth alerting on (cron-group failure, license expiring,
secret-resolution failure) call `notify()` directly. Audit events are
re-fired into notifications by the enterprise audit recorder itself, so
no double-wiring is needed at call sites.
"""
from application.enterprise import has_feature, run_hook


def notify(event_type, **context):
    """
    Emit one notifiable event. `event_type` is a dot-separated identifier
    (`cron.group.failed`, `license.expiring`, `secret.resolution_failed`).

    Keys the dispatcher understands:
      severity ('info' | 'warning' | 'error' | 'critical'),
      title, message, source, affected, details (dict), runbook_url,
      dedup_key (string — events with the same key share cooldown state).
    """
    if not has_feature('notifications'):
        return
    try:
        run_hook('notify_event', event_type, **context)
    except Exception:  # pylint: disable=broad-exception-caught
        # A notification failure must never break the observed event path.
        pass
