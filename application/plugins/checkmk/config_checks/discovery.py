"""
Service discovery on the hosts of a configuration check topic, the one
action of the Configuration Checks page that writes to Checkmk.

Checkmk runs it as a bulk discovery background job; only one can run at a
time. The job is started right away, a thread of the web process waits for
it, activates the changes when asked to and logs the result under
Settings, Log with source Checkmk.
"""
import re
import threading
import time

from application import app, log

# What the discovery may change, as the bulk discovery names it, with the
# label of the page. Unchecked options leave that part as it is.
OPTIONS = (
    ('monitor_undecided_services', 'Add new services'),
    ('remove_vanished_services', 'Remove vanished services'),
    ('update_host_labels', 'Update host labels'),
)
START_URL = 'domain-types/discovery_run/actions/bulk-discovery-start/invoke'
POLL_SECONDS = 5
MAX_WAIT_SECONDS = 3600
# The job ends as finished even when the discovery of hosts failed; only
# its summary line tells
_HOST_SUMMARY = re.compile(r'Hosts: \d+ total \(\d+ succeeded, \d+ skipped, (\d+) failed\)')


def request_body(hosts, options):
    """The bulk discovery request for ``hosts`` with the chosen ``options``"""
    return {
        'hostnames': list(hosts),
        'options': {key: key in options for key, _label in OPTIONS},
        'do_full_scan': True,
        'bulk_size': 10,
        'ignore_errors': True,
    }


def start(cmk, hosts, options):
    """
    Start the bulk discovery, returns the id of its background job.
    Raises CmkException when Checkmk refuses, for example while another
    bulk discovery runs.
    """
    # pylint: disable=import-outside-toplevel
    from ..cmk2 import CmkException
    data, headers = cmk.request(START_URL, method='POST',
                                data=request_body(hosts, options))
    job_id = data.get('id')
    if not job_id:
        raise CmkException(f"Checkmk started no discovery: "
                           f"{headers.get('error') or data or headers}")
    return job_id


def job_status(cmk, job_id):
    """``(active, status)`` of the background job ``job_id``"""
    data, _headers = cmk.request(f'objects/background_job/{job_id}', method='GET')
    extensions = data.get('extensions', {}) or {}
    return bool(extensions.get('active')), extensions.get('status', {}) or {}


def wait(cmk, job_id, sleep=time.sleep, clock=time.monotonic):
    """The status of the job once it ended; raises TimeoutError"""
    deadline = clock() + MAX_WAIT_SECONDS
    while True:
        active, status = job_status(cmk, job_id)
        if not active:
            return status
        if clock() > deadline:
            raise TimeoutError(f"the discovery job {job_id} still runs after "
                               f"{MAX_WAIT_SECONDS // 60} minutes")
        sleep(POLL_SECONDS)


def summarize(status):
    """
    ``(failed, lines)`` from the status of an ended job: failed when the
    job did not finish, raised an exception or failed on a host.
    """
    info = status.get('log_info', {}) or {}
    exceptions = info.get('JobException', []) or []
    lines = [str(line) for line in (info.get('JobProgressUpdate', []) or [])[-15:]
             + (info.get('JobResult', []) or []) + exceptions]
    failed = bool(exceptions) or status.get('state') not in ('finished', None) \
        or any(int(match.group(1)) for line in lines
               if (match := _HOST_SUMMARY.search(line)))
    return failed, lines


def finish(account, job_id, hosts, options, activate, user):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """
    Wait for the job, activate the changes if asked and log the result.
    Runs in its own thread, so it opens its own application context.
    """
    # pylint: disable=import-outside-toplevel
    from ..cmk2 import CMK2, CmkException
    from ..inits import activate_changes
    with app.app_context():
        details = [('account', account), ('started_by', user),
                   ('hosts', ', '.join(hosts)), ('job', job_id),
                   ('options', ', '.join(label for key, label in OPTIONS
                                         if key in options) or 'none')]
        try:
            status = wait(CMK2(account), job_id)
            failed, lines = summarize(status)
            details.append(('state', status.get('state', '')))
            details += [('output', line) for line in lines]
            if activate and not failed:
                activated = activate_changes(account)
                details.append(('activate_changes', 'done' if activated else 'failed'))
                failed = not activated
        except (CmkException, TimeoutError, OSError) as exp:
            failed = True
            details.append(('error', str(exp)))
        if failed and not any(key == 'error' for key, _value in details):
            details.append(('error', 'the discovery or the activation failed'))
        log.log(f"Checkmk service discovery on {len(hosts)} host(s): "
                f"{'failed' if failed else 'done'}",
                source='Checkmk', details=details)


def run(account, hosts, options, activate, user):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """
    Start the discovery of ``hosts`` and leave the rest to a thread.
    Returns the job id; raises CmkException when Checkmk refuses the start.
    """
    # pylint: disable=import-outside-toplevel
    from ..cmk2 import CMK2
    job_id = start(CMK2(account), hosts, options)
    log.log(f"Checkmk service discovery started on {len(hosts)} host(s)",
            source='Checkmk',
            details=[('account', account), ('started_by', user),
                     ('hosts', ', '.join(hosts)), ('job', job_id)])
    threading.Thread(target=finish, daemon=True, name=f'cmk-discovery-{job_id}',
                     args=(account, job_id, list(hosts), list(options),
                           activate, user)).start()
    return job_id
