"""
Background runner for the Checkmk rule optimization analysis.

The analysis renders every rule for every host and then walks the hosts a
second time to count label coverage. On a large inventory that takes far
longer than a web request may, so the web interface starts it in a
thread and reads state and result from ``CheckmkRuleAnalysis``.

Same shape as the Ansible playbook runner: start, return the document,
let the page poll it.
"""
import threading
from datetime import datetime

from application import app, logger
from application.plugins.checkmk.models import CheckmkRuleAnalysis

# A run that never wrote a result — the process was restarted mid-run, or
# the thread died in a way no except could catch. Older than this and the
# page offers a fresh start instead of waiting forever.
STALE_RUN_MINUTES = 120


def get_analysis(account=''):
    """The stored analysis for an account, or None."""
    return CheckmkRuleAnalysis.objects(account=account or '').first()


def is_stale(analysis):
    """
    Whether a 'running' analysis has been running implausibly long. The
    thread is not supervised — a restarted process leaves the document
    behind, and nothing would ever move it out of 'running'.
    """
    if not analysis or analysis.state != 'running' or not analysis.started_at:
        return False
    age = datetime.now() - analysis.started_at
    return age.total_seconds() > STALE_RUN_MINUTES * 60


def start_analysis(account='', min_hosts=10, top=20):
    """
    Start the analysis in the background and return its document.

    Returns None when one is already running for this account — the
    analysis is expensive and running it twice at once buys nothing.
    """
    account = account or ''
    analysis = get_analysis(account)
    if analysis and analysis.state == 'running' and not is_stale(analysis):
        return None
    if not analysis:
        analysis = CheckmkRuleAnalysis()
        analysis.account = account
    analysis.state = 'running'
    analysis.error = ''
    analysis.started_at = datetime.now()
    analysis.finished_at = None
    analysis.min_hosts = min_hosts
    analysis.findings = []
    analysis.save()

    thread = threading.Thread(
        target=_execute,
        args=(analysis.pk, account, min_hosts, top),
        daemon=True,
        name=f'cmk-rule-analysis-{account or "all"}',
    )
    thread.start()
    return analysis


def _execute(analysis_id, account, min_hosts, top):
    """Run the analysis and write the result back."""
    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from application.plugins.checkmk.cmk_rules import findings_for_storage
        from application.plugins.checkmk.inits import analyse_rules
        analysis = CheckmkRuleAnalysis.objects(pk=analysis_id).first()
        if not analysis:
            return
        try:
            results = analyse_rules(account or None, min_hosts=min_hosts,
                                    top=top)
            analysis.findings = findings_for_storage(results)
            analysis.state = 'done'
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Whatever goes wrong in here must end up on the page. A
            # thread that dies silently leaves the run at "running"
            # forever, and nobody would know why.
            logger.debug("Rule analysis failed: %s", error)
            analysis.error = str(error)
            analysis.state = 'failed'
        analysis.finished_at = datetime.now()
        analysis.save()
