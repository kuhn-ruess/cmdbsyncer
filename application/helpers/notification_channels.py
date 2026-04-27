"""
Channel sender registry.

OSS ships the email sender. Enterprise registers Slack / MS Teams /
generic Webhook senders at activation time via
:func:`register_channel_sender`.

Each sender is `send(channel, payload)` where ``payload`` is the dict
the dispatcher passes (``title``, ``message``, ``source``, ``details``,
``event_type`` …).
"""
from application.helpers.get_account import (
    AccountNotFoundError,
    get_account_by_name,
)


def resolve_account(channel, required=True):
    """Return the resolved Account dict for ``channel``, or None."""
    name = (channel.account or '').strip()
    if not name:
        if required:
            raise RuntimeError(
                f"Channel {channel.name!r} has no Account configured"
            )
        return None
    try:
        return get_account_by_name(name)
    except AccountNotFoundError as exc:
        raise RuntimeError(
            f"Channel {channel.name!r}: Account {name!r} not found or disabled"
        ) from exc


def _email_html(payload):
    title = payload.get('title') or 'Notification'
    message = payload.get('message') or ''
    # For log-source events the dispatcher uses the log message as both
    # title and message — render the body paragraph only when it would
    # add information beyond the H2 header.
    body_html = (f"<p style='white-space:pre-wrap'>{message}</p>"
                 if message and message != title else '')
    rows = []
    for key in ('event_type', 'source', 'target', 'outcome',
                'actor_name', 'actor_ip', 'trace_id'):
        if value := payload.get(key):
            rows.append(
                f"<tr><td style='padding:4px 8px;color:#666;'>{key}</td>"
                f"<td style='padding:4px 8px;'><code>{value}</code></td></tr>"
            )
    for key, value in (payload.get('details') or {}).items():
        rows.append(
            f"<tr><td style='padding:4px 8px;color:#666;'>{key}</td>"
            f"<td style='padding:4px 8px;'><code>{value}</code></td></tr>"
        )
    return (f"<h2>{title}</h2>"
            f"{body_html}"
            f"<table style='border-collapse:collapse;border:1px solid #ddd;'>"
            f"{''.join(rows)}</table>")


def _email_send(channel, payload):
    # We deliberately do NOT route through application.modules.email.send_email
    # here — that helper spawns its own daemon Thread for SMTP, which is fine
    # from a web request but breaks for the notification path:
    #   * the dispatcher already runs in a worker thread, so wrapping again
    #     gains nothing;
    #   * for atexit-triggered flushes (CLI runs) the spawned Thread is
    #     killed before it can talk to the SMTP server, so the mail
    #     silently never leaves the box. We send synchronously instead so
    #     exceptions surface and the call blocks until the SMTP exchange
    #     is over.
    # pylint: disable=import-outside-toplevel
    from application import app, log, mail
    from flask import render_template
    from flask_mail import Message

    recipients = [r.strip() for r in (channel.email_recipients or '').split(',')
                  if r.strip()]
    if not recipients:
        raise RuntimeError(
            f"Email channel {channel.name!r} has no recipients configured"
        )
    subject = (f"{(channel.email_subject_prefix or '[CMDBsyncer]').strip()} "
               f"{payload.get('title') or 'Notification'}")

    with app.app_context():
        body_html = render_template(
            'email/notification.html',
            notification=payload, rendered_html=_email_html(payload),
        )
        for recipient in recipients:
            msg = Message(
                f"{app.config.get('MAIL_SUBJECT_PREFIX', '')} {subject}".strip(),
                sender=app.config.get('MAIL_SENDER'),
                recipients=[recipient],
            )
            msg.html = body_html
            mail.send(msg)

    # Surface the delivery in the syncer Log. The dispatcher's thread-
    # local guard prevents this from re-entering the dispatcher.
    log.log(
        "Notification email sent",
        source='notification',
        details=[
            ('channel', channel.name),
            ('recipients', ', '.join(recipients)),
            ('subject', subject),
        ],
    )


_SENDERS = {'email': _email_send}


def register_channel_sender(channel_type, sender):
    """Idempotent override-or-add for ``channel_type``."""
    _SENDERS[channel_type] = sender


def send(channel, payload):
    """Dispatch ``payload`` through the registered sender for ``channel.type``."""
    sender = _SENDERS.get(channel.type)
    if sender is None:
        raise RuntimeError(f"Unknown notification channel type: {channel.type}")
    return sender(channel, payload)
