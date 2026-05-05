# Version 1.2
"""
Email helper.

`send_email` enqueues the message onto a single background worker
that logs any SMTP failure into the syncer Log, instead of spawning
a fresh daemon thread per call (which silently dropped errors and
made retries / auditing impossible).

The worker mirrors the pattern in `helpers/notification_dispatch`:
one daemon thread, an atexit drain so CLI invocations don't lose
mail enqueued just before exit.
"""
import atexit
import logging
import queue
import threading
import time

from flask import current_app, render_template
from flask_mail import Message
from application import mail

_logger = logging.getLogger(__name__)

EXIT_DRAIN_TIMEOUT_SECONDS = 30

_queue = queue.Queue(maxsize=1000)
_worker_started = threading.Lock()
_worker_running = False  # pylint: disable=invalid-name


def _start_worker():
    global _worker_running  # pylint: disable=global-statement
    with _worker_started:
        if _worker_running:
            return
        thread = threading.Thread(
            target=_worker_loop, name='email-sender', daemon=True,
        )
        thread.start()
        _worker_running = True


def _worker_loop():
    while True:
        app, msg, recipient = _queue.get()
        try:
            with app.app_context():
                mail.send(msg)
        except Exception as exp:  # pylint: disable=broad-exception-caught
            _logger.exception("Email send to %s failed", recipient)
            try:
                from application import log as syncer_log  # pylint: disable=import-outside-toplevel
                syncer_log.log(
                    f"Email send to {recipient} failed: {exp}",
                    source='email',
                    details=[('error', str(exp)), ('recipient', recipient)],
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        finally:
            _queue.task_done()


def _drain_on_exit():
    if not _worker_running or _queue.unfinished_tasks == 0:
        return
    deadline = time.monotonic() + EXIT_DRAIN_TIMEOUT_SECONDS
    while _queue.unfinished_tasks > 0 and time.monotonic() < deadline:
        time.sleep(0.05)


atexit.register(_drain_on_exit)


def send_email(to, subject, template, **kwargs):
    """Public entry: render template + enqueue for the worker."""
    try:
        app = current_app._get_current_object()  # pylint: disable=protected-access
    except RuntimeError:
        app = kwargs['ext_app']
    send_email_inner(to, subject, template, app, **kwargs)


def send_email_inner(to, subject, template, app, **kwargs):
    """Build the Message and hand it to the worker queue."""
    with app.app_context():

        sender = kwargs.get('SENDER', app.config['MAIL_SENDER'])

        msg = Message(
            app.config['MAIL_SUBJECT_PREFIX'] + ' ' + subject,
            sender=sender,
            recipients=[to]
        )
        # msg.body = render_template(template + '.txt', **kwargs)
        msg.html = render_template(template + '.html', **kwargs)
        if 'attachment_file' in kwargs:
            msg.attach(
                kwargs['attachment_name'],
                kwargs['attachment_mime'],
                kwargs['attachment_file']
            )

        if 'attachment_path' in kwargs:
            with app.open_resource(kwargs['attachment_path']) as attachment:
                msg.attach(
                    kwargs['attachment_name'],
                    kwargs['attachment_mime'],
                    attachment.read()
                )

        _start_worker()
        try:
            _queue.put_nowait((app, msg, to))
        except queue.Full:
            _logger.warning("Email queue full, dropping message to %s", to)
            try:
                from application import log as syncer_log  # pylint: disable=import-outside-toplevel
                syncer_log.log(
                    f"Email queue full, dropped message to {to}",
                    source='email',
                    details=[('recipient', to), ('subject', subject)],
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass
