"""
Notification Hub — in-memory dispatch queue.

No database hop on the hot path. The HTTP handler validates the
payload, calls `enqueue(event)` and returns a job id; a single
background worker thread pulls from a `queue.Queue` and runs the
resolver. Completed jobs land in a bounded ring buffer
(`collections.deque`) that the Admin UI reads for display.

Trade-off vs. a Mongo-backed queue: nothing is persisted, so a hard
process kill loses in-flight jobs and the ring-buffer history. The
Checkmk caller already retries failed notifications, and the admin
can re-submit any missing event via `cmdbsyncer notify test_dispatch`;
the speed + no-DB-pressure win on the hot path is the whole point.
"""
import itertools
import logging
import threading
import uuid
from collections import deque
from datetime import datetime
from queue import Queue, Empty

from application import app

from .resolver import resolve_and_dispatch

log = logging.getLogger(__name__)


# Tunables — overridable from local_config.py. Defaults sized for
# "tens of thousands of events/hour" without pulling in Redis.
_QUEUE_MAXSIZE = int(app.config.get('NOTIFY_QUEUE_MAXSIZE', 10_000))
_HISTORY_SIZE = int(app.config.get('NOTIFY_HISTORY_SIZE', 1_000))
_MAX_ATTEMPTS = int(app.config.get('NOTIFY_MAX_ATTEMPTS', 3))

# Work queue is just a Queue — fast, lock-protected inside Python.
_work_queue = Queue(maxsize=_QUEUE_MAXSIZE)

# Ring buffer of completed (done/failed) jobs. deque with maxlen
# evicts the oldest entry on overflow, so this is O(1) regardless of
# throughput. Guarded by `_history_lock` because the admin reads it
# from request threads while the worker writes to it.
_history = deque(maxlen=_HISTORY_SIZE)
_history_lock = threading.Lock()

# "In flight" / "queued but not yet picked up" rows accessed by job
# id, so `GET /dispatch/<id>` can respond before the job reaches the
# history deque.
_inflight = {}
_inflight_lock = threading.Lock()

# Monotonic counter for user-friendly short ids alongside the uuid.
_counter = itertools.count(1)

_worker_started = False  # pylint: disable=invalid-name
_worker_lock = threading.Lock()


def enqueue(event):
    """Accept an event and schedule it. Returns the job dict.

    Raises RuntimeError if the queue is saturated — the caller should
    turn that into a 503 so upstream senders back off.
    """
    job_id = uuid.uuid4().hex
    job = {
        'id':          job_id,
        'seq':         next(_counter),
        'status':      'queued',
        'source':      event.get('source') or '',
        'event_type':  event.get('event_type') or '',
        'host':        event.get('host') or '',
        'service':     event.get('service') or '',
        'state':       event.get('state') or '',
        'received_at': datetime.utcnow(),
        'started_at':  None,
        'finished_at': None,
        'attempts':    0,
        'error':       '',
        'outcomes':    [],
        'event':       event,
    }
    with _inflight_lock:
        _inflight[job_id] = job
    try:
        _work_queue.put_nowait(job)
    except Exception as exp:  # pylint: disable=broad-exception-caught
        with _inflight_lock:
            _inflight.pop(job_id, None)
        raise RuntimeError('notify queue is full') from exp
    _ensure_worker()
    return job


def get_job(job_id):
    """Return the current snapshot for `job_id`, or None."""
    with _inflight_lock:
        in_flight = _inflight.get(job_id)
    if in_flight is not None:
        return dict(in_flight)
    with _history_lock:
        for entry in _history:
            if entry.get('id') == job_id:
                return dict(entry)
    return None


def snapshot():
    """Point-in-time view for the admin dashboard."""
    with _inflight_lock:
        in_flight = list(_inflight.values())
    with _history_lock:
        recent = list(_history)
    return {
        'pending':   _work_queue.qsize(),
        'maxsize':   _QUEUE_MAXSIZE,
        'history':   _HISTORY_SIZE,
        'inflight':  in_flight,
        'recent':    list(reversed(recent)),  # newest first
    }


def clear_history():
    """Operator action — drop the recent-jobs buffer."""
    with _history_lock:
        _history.clear()


def _ensure_worker():
    """Start the queue thread on first use. Idempotent per process."""
    global _worker_started  # pylint: disable=global-statement
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(
            target=_worker_loop,
            name='notify-queue-worker',
            daemon=True,
        )
        thread.start()
        _worker_started = True
        log.info('notify queue worker started (maxsize=%d, history=%d)',
                 _QUEUE_MAXSIZE, _HISTORY_SIZE)


def _worker_loop():
    while True:
        try:
            job = _work_queue.get(timeout=1.0)
        except Empty:
            continue
        try:
            _run_job(job)
        except Exception as exp:  # pylint: disable=broad-exception-caught
            log.exception('notify worker crashed on job %s: %s',
                          job.get('id'), exp)
        finally:
            _work_queue.task_done()


def _run_job(job):
    job['attempts'] += 1
    job['status'] = 'processing'
    job['started_at'] = datetime.utcnow()
    try:
        outcomes = resolve_and_dispatch(job['event'])
        job['outcomes'] = [
            {'contact': c, 'channel': ch, 'outcome': out,
             'error': err or ''}
            for c, ch, out, err in outcomes
        ]
        any_failed = any(o['outcome'] == 'failed' for o in job['outcomes'])
        job['status'] = 'failed' if any_failed else 'done'
        job['error'] = ''
    except Exception as exp:  # pylint: disable=broad-exception-caught
        log.warning('notify job %s failed: %s', job['id'], exp)
        job['error'] = str(exp)
        if job['attempts'] < _MAX_ATTEMPTS:
            # Requeue in place — fast path, no persistence.
            job['status'] = 'queued'
            job['started_at'] = None
            try:
                _work_queue.put_nowait(job)
                return
            except Exception:  # pylint: disable=broad-exception-caught
                job['status'] = 'failed'
        else:
            job['status'] = 'failed'
    finally:
        job['finished_at'] = datetime.utcnow()

    # Terminal state — drop from inflight, push to history.
    with _inflight_lock:
        _inflight.pop(job['id'], None)
    with _history_lock:
        _history.append(job)
