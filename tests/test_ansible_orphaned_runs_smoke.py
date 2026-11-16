"""
Playbook runs whose process is gone do not stay 'running': the run history
marks them aborted, and a fire rule starts them again. A run that fails
while it is being prepared ends as failure.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import os
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from application.plugins.ansible import playbook_rules, runner
from application.plugins.ansible.models import AnsibleRunStats

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})

HOST = socket.gethostname()
NOW = datetime.now()

# A process which is gone for sure: one that already ended
gone = subprocess.Popen(['true'])
gone.wait()


def run(**fields):
    """A run record of the fire rule 'r1' against srv01"""
    stats = AnsibleRunStats(playbook='site.yml', target_host='srv01', source='rule',
                            triggered_by='rule:r1', started_at=NOW,
                            status='running', **fields)
    stats.save()
    return stats


dead = run(pid=gone.pid, runner_host=HOST, log='PLAY [all]\\n')
other_host = run(pid=gone.pid, runner_host='other-machine')
preparing = run(runner_host=HOST)
stuck_preparing = run(runner_host=HOST)
AnsibleRunStats.objects(pk=stuck_preparing.pk).update(
    set__started_at=NOW - timedelta(hours=1))
legacy = run(pid=gone.pid)

# A live ansible-playbook process counts as alive
with patch.object(runner, '_ansible_process_alive', return_value=True):
    eq(runner.run_is_orphaned(run(pid=gone.pid, runner_host=HOST)), False,
       'live process')

check('/admin/ansiblerunstats/', 200)
for stats, expected, what in (
        (dead, 'aborted', 'dead process'),
        (other_host, 'running', 'run of another machine'),
        (preparing, 'running', 'run still preparing'),
        (stuck_preparing, 'aborted', 'run stuck preparing'),
        (legacy, 'aborted', 'run without machine'),
):
    stats.reload()
    eq(stats.status, expected, what)
dead.reload()
eq(dead.log.startswith('PLAY [all]'), True, 'log kept')
eq('Its result is unknown' in dead.log, True, 'note in the log')
eq(dead.ended_at is not None, True, 'end set')

# The detail page and its progress poll mark the one run they show
single = run(pid=gone.pid, runner_host=HOST)
check(f'/admin/ansiblerunstats/details/?id={single.id}', 200)
single.reload()
eq(single.status, 'aborted', 'run of the detail page')
polled = run(pid=gone.pid, runner_host=HOST)
progress = check(f'/admin/ansiblerunstats/progress/{polled.id}', 200).get_json()
eq(progress['running'], False, 'progress of a run without process')
check('/admin/ansiblerunstats/details/?id=not-an-id', 302)

# An aborted run fires again, a failed one does not
eq(playbook_rules._already_fired('r1', 'srv01', 'site.yml'), True, 'running counts')
AnsibleRunStats.objects(status='running').delete()
eq(playbook_rules._already_fired('r1', 'srv01', 'site.yml'), False, 'aborted counts not')
failed = run()
AnsibleRunStats.objects(pk=failed.pk).update(set__status='failure')
eq(playbook_rules._already_fired('r1', 'srv01', 'site.yml'), True, 'failure counts')

# A failure while preparing ends the run and removes its temp dir
prepared = run(runner_host=HOST)
made = []
real_mkdtemp = runner.tempfile.mkdtemp


def mkdtemp(**kwargs):
    made.append(real_mkdtemp(**kwargs))
    return made[-1]


with patch.object(runner.tempfile, 'mkdtemp', side_effect=mkdtemp), \\
        patch.object(runner, '_write_run_inventory_spec', side_effect=OSError('disk full')):
    runner._execute(prepared.pk, {'playbook': 'site.yml'}, Path(os.getcwd()), 'ansible')
prepared.reload()
eq(prepared.status, 'failure', 'status after a failed preparation')
eq(prepared.log, 'Runner error: disk full', 'log after a failed preparation')
eq(prepared.ended_at is not None, True, 'end after a failed preparation')
eq(os.path.exists(made[0]), False, 'temp dir removed')

print('ORPHANED_RUNS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AnsibleOrphanedRunsTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_orphaned_runs(self):
        """Runs without process end as aborted and fire again."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('ORPHANED_RUNS_OK', result.stdout)
