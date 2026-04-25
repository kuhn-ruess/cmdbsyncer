"""
Audit event emitter.

The OSS entry point for audit logging. All call sites use `audit()`; the
actual persistence happens in the enterprise `audit_log` module when its
license feature is active. In community installs the hook returns `None`
and the call is a no-op.

Web-request context (current user, IP, URL, trace headers) is attached
automatically when the caller is inside a Flask request — avoids
repeating the boilerplate at every call site.
"""
from application.enterprise import has_feature, run_hook


def web_context():
    """
    Best-effort extraction of the current HTTP context. Swallows all
    errors so audit emission never breaks the request path.
    """
    try:
        from flask import request, has_request_context  # pylint: disable=import-outside-toplevel
        from flask_login import current_user  # pylint: disable=import-outside-toplevel
    except ImportError:
        return {}
    try:
        if not has_request_context():
            return {}
    except RuntimeError:
        return {}
    ctx = {
        'request_method': request.method,
        'request_path': request.path,
        'actor_ip': request.remote_addr,
        'user_agent': request.headers.get('User-Agent'),
    }
    for header in ('X-Request-ID', 'X-Cloud-Trace-Context',
                   'X-Amzn-Trace-Id', 'traceparent'):
        trace = request.headers.get(header)
        if trace:
            ctx['trace_id'] = trace
            break
    try:
        if current_user and current_user.is_authenticated:
            ctx['actor_type'] = 'user'
            ctx['actor_id'] = str(current_user.id)
            ctx['actor_name'] = current_user.email or current_user.name
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return ctx


def audit(event_type, **context):
    """
    Emit one audit event. `event_type` is a dot-separated identifier
    (e.g. `user.login.success`, `account.updated`, `webhook.rejected`).

    Optional context keys the enterprise recorder understands:
      target_type, target_id, target_name, changes, metadata,
      message, outcome ('success' | 'failure'),
      actor_type, actor_id, actor_name, actor_ip.

    Any of those override the auto-extracted web context, so callers
    that run outside a request (CLI, cron, MongoEngine signal) can
    still set the actor themselves.
    """
    if not has_feature('audit_log'):
        return
    payload = web_context()
    payload.update(context)
    try:
        run_hook('audit_event', event_type, **payload)
    except Exception:  # pylint: disable=broad-exception-caught
        # An audit write must never break the business path it observes.
        # Failures are surfaced via the enterprise module's own logger.
        pass
