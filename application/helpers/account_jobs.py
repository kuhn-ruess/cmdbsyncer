"""
Run Jobs defined by Account: the account lists the jobs of its plugin
it runs, in that order, and its role limits which. Without a list it
imports or inventorizes, as the role says.
"""
import inspect

from application import cron_register
from application.helpers.cron import import_register
from application.helpers.get_account import get_account_by_name
from application.helpers.plugins import plugin_jobs
from application.helpers.task_status import take_task_failure
from application.models.account import account_restrictions, object_types

ACCOUNT_JOBS_JOB = 'Run Jobs defined by Account'

# The kinds of jobs a role does not allow
FORBIDDEN_KINDS = {
    'import': {'inventorize'},
    'inventorize': {'import'},
    'export': {'import', 'inventorize'},
}


class AccountJobsError(ValueError):
    """The account can not run its jobs"""


def account_job_settings(account):
    """
    Name, type, role and jobs of an Account document, the way
    get_account_by_name() resolves them: a child account takes type and
    jobs of its parent where it has none.
    """
    parent = account.parent if account.is_child else None
    return {
        'name': account.name,
        'typ': account.type or (parent.type if parent else None),
        'restrict_to': account.restrict_to or '',
        'account_jobs': list(account.account_jobs
                             or (parent.account_jobs if parent else []) or []),
    }


def job_kind(job):
    """'import', 'inventorize' or 'other' for a cron job name"""
    function = cron_register.get(job)
    if function is None:
        return 'other'
    for entries in import_register.values():
        for entry in entries:
            if function is entry['import']:
                return 'import'
            if function is entry['inventorize']:
                return 'inventorize'
    return 'other'


def several_imports(jobs):
    """Whether the jobs import more than once, devices and VMs for example"""
    return sum(job_kind(job) == 'import' for job in jobs or []) > 1


def _default_function(settings):
    """What an account without a job list runs: import or inventorize"""
    name, account_type = settings['name'], settings.get('typ')
    role = settings.get('restrict_to') or ''
    if role == 'export':
        raise AccountJobsError(f"Account {name} is an export target, pick its jobs")
    entries = import_register.get(account_type)
    if not entries:
        raise AccountJobsError(f"Account {name}: accounts of type {account_type} "
                               "have no import, pick the jobs of the account")
    operation = 'inventorize' if role == 'inventorize' else 'import'
    function = entries[0][operation]
    if not function:
        raise AccountJobsError(f"Account {name}: {account_type} can not {operation}, "
                               "pick the jobs of the account")
    return function


def job_problems(settings):
    """Why jobs of the account list can not run with it"""
    name, account_type = settings['name'], settings.get('typ')
    role = settings.get('restrict_to') or ''
    allowed = plugin_jobs(account_type)
    forbidden = FORBIDDEN_KINDS.get(role, set())
    problems = []
    for job in settings.get('account_jobs') or []:
        if job not in allowed:
            problems.append(f"Account {name}: {job} is no job of accounts "
                            f"of type {account_type}")
        elif job_kind(job) in forbidden:
            problems.append(f"Account {name}: the role "
                            f"{dict(account_restrictions)[role]} does not allow {job}")
    return problems


def jobs_to_run(settings):
    """[(name, function)] the account runs, raises AccountJobsError"""
    if problems := job_problems(settings):
        raise AccountJobsError(problems[0])
    if jobs := settings.get('account_jobs'):
        return [(job, cron_register[job]) for job in jobs]
    return [('', _default_function(settings))]


def creates(account):
    """
    What import jobs with the Account document put into the syncer, for
    the cron group list: the job name says hosts or objects, the account
    decides it. None for an export target.
    """
    role = account.restrict_to or ''
    if role == 'export':
        return None
    if role == 'inventorize':
        return 'inventory'
    if not account.is_object:
        return 'hosts'
    kind = dict(object_types).get(account.object_type)
    return f'objects: {kind}' if kind and account.object_type != 'auto' else 'objects'


def is_import_job(command):
    """Whether the cron command may import or inventorize with its account"""
    return command == ACCOUNT_JOBS_JOB or job_kind(command) != 'other'


def run_account_jobs(account=None, debug=False):
    """Run the jobs of the account in their order, stop at the first failing"""
    if not account:
        raise AccountJobsError(f"{ACCOUNT_JOBS_JOB} needs an account")
    jobs = jobs_to_run(get_account_by_name(account))
    for job, function in jobs:
        if len(jobs) > 1:
            print(f"Job: {job}")
        if 'debug' in inspect.signature(function).parameters:
            function(account=account, debug=debug)
        else:
            function(account=account)
        if (failure := take_task_failure()) is not None:
            raise failure
