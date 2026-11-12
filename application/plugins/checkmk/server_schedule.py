"""
Weekly runs of the Checkmk Server Settings, each settings on its own
weekday and hour: set the newest patch release of its Checkmk version
and start Manage OMD Server for the servers of its sites.

The cron job runs whatever is due when it is called, so its cron group
runs every 15 minutes. A run that is missed on its day waits a week.

Settings can depend on others, production on test for example: they
run only after a success of the other one within the last week, and
take the version it ended with instead of the newest one.
"""
from datetime import datetime, timedelta

import requests
from mongoengine.errors import DoesNotExist

from application import log
from application.helpers.task_status import task_failed
from application.modules.debug import ColorCodes as CC
from application.plugins.ansible.runner import run_playbook
from .models import CheckmkSettings, CheckmkSite, schedule_weekdays
from . import download_catalog

PLAYBOOK = 'cmk_server_mngmt.yml'
LOG_SOURCE = 'Checkmk Server'
# How old the success of a dependency may be
DEPENDENCY_MAX_AGE = timedelta(days=7)


class SkipRun(Exception):
    """The run of a settings is not done, for the reason given"""


def site_servers(setting):
    """The servers of the enabled sites that use ``setting``, sorted"""
    return sorted({site.server_address for site in
                   CheckmkSite.objects(settings_master=setting, enabled=True)})


def is_due(setting, now):
    """Whether the weekly run of ``setting`` is due at ``now``"""
    if not setting.schedule_weekday:
        return False
    if not (setting.schedule_update_version or setting.schedule_run_playbook):
        return False
    if schedule_weekdays[now.weekday()][0] != setting.schedule_weekday:
        return False
    slot = now.replace(hour=int(setting.schedule_hour or 0),
                       minute=0, second=0, microsecond=0)
    if now < slot:
        return False
    return not setting.schedule_last_run or setting.schedule_last_run < slot


def depends_on(setting):
    """
    The settings ``setting`` depends on, None without. Raises SkipRun when
    they are gone, as after an import without them.
    """
    try:
        return setting.schedule_depends_on
    except DoesNotExist as exp:
        raise SkipRun("the settings it depends on no longer exist") from exp


def dependency_chain(setting):
    """
    The settings ``setting`` depends on, nearest first. Raises ValueError
    when the chain leads back to ``setting``.
    """
    chain = []
    seen = {setting.id}
    try:
        current = depends_on(setting)
        while current is not None:
            if current.id in seen:
                raise ValueError(f"{setting.name} depends on itself through "
                                 f"{' -> '.join(dep.name for dep in chain) or current.name}")
            seen.add(current.id)
            chain.append(current)
            current = depends_on(current)
    except SkipRun:
        pass
    return chain


def _check_dependency(setting, now):
    """
    The version the dependency of ``setting`` ended with, None without a
    dependency. Raises SkipRun when it did not succeed in the last week.
    """
    reference = depends_on(setting)
    if reference is None:
        return None
    # Fresh from the database: it may have run in this pass
    dependency = CheckmkSettings.objects(id=reference.id).first()
    if dependency is None:
        raise SkipRun("the settings it depends on no longer exist")
    if dependency.schedule_last_status != 'success':
        reason = dependency.schedule_last_message or 'it did not run yet'
        raise SkipRun(f"{dependency.name} did not succeed: {reason}")
    if not dependency.schedule_last_run or \
            dependency.schedule_last_run < now - DEPENDENCY_MAX_AGE:
        raise SkipRun(f"{dependency.name} did not run in the last 7 days")
    return dependency.schedule_last_version or dependency.cmk_version


def _set_version(setting, version, details):
    """Set the CMK Version of ``setting``"""
    details.append(('version_before', setting.cmk_version or ''))
    details.append(('version_after', version))
    if version == setting.cmk_version:
        print(f"{CC.OKBLUE} *{CC.ENDC} {setting.name}: {version} is up to date")
        return
    print(f"{CC.OKGREEN} *{CC.ENDC} {setting.name}: "
          f"{setting.cmk_version} set to {version}")
    CheckmkSettings.objects(id=setting.id).update_one(set__cmk_version=version)
    setting.cmk_version = version


def _version_of_dependency(setting, version):
    """The version of the dependency, refused for another major release"""
    if download_catalog.major_of(setting.cmk_version) != \
            download_catalog.major_of(version):
        raise ValueError(f"the settings it depends on ended with {version}, "
                         f"another major release than {setting.cmk_version}")
    return version


def _run_playbook(setting, details):
    """Manage OMD Server for the sites of ``setting``, raises RuntimeError"""
    if setting.ask_ssh_password:
        raise RuntimeError("the settings ask for the SSH password, which a "
                           "scheduled run can't do; start it with Run Playbook")
    servers = site_servers(setting)
    if not servers:
        print(f"{CC.WARNING} *{CC.ENDC} {setting.name}: no enabled site uses it")
        details.append(('servers', 'none, no enabled site uses these settings'))
        return
    details.append(('servers', ', '.join(servers)))
    print(f"{CC.OKGREEN} *{CC.ENDC} {setting.name}: Manage OMD Server "
          f"for {', '.join(servers)}")
    log.log(f"Weekly run of {setting.name}: Manage OMD Server started",
            source=LOG_SOURCE,
            details=[('settings', setting.name), ('servers', ', '.join(servers)),
                     ('version', setting.cmk_version or '')])
    # One run after the other: a server may have sites of several settings.
    stats = run_playbook(
        PLAYBOOK,
        target_host=','.join(servers),
        provider=f'cmk_sites:{setting.name}',
        ssh_private_key=setting.get_server_ssh_key(),
        source='cron',
        triggered_by='cron',
        wait=True,
    )
    details.append(('ansible_run', str(stats.pk)))
    if stats.status != 'success':
        raise RuntimeError(f"Manage OMD Server ended with {stats.status}, "
                           f"see Ansible run {stats.pk}")


def _finish(setting, now, status, message, details):
    """Store and log the result of the run of ``setting``"""
    values = {'set__schedule_last_status': status,
              'set__schedule_last_message': message}
    if status == 'success':
        values['set__schedule_last_version'] = setting.cmk_version
    CheckmkSettings.objects(id=setting.id).update_one(**values)
    if status == 'success':
        print(f"{CC.OKGREEN} *{CC.ENDC} {setting.name}: {message}")
    else:
        print(f"{CC.FAIL} *{CC.ENDC} {setting.name}: {message}")
        details.append(('error', message))
    log.log(f"Weekly run of {setting.name}: {status}", source=LOG_SOURCE,
            details=[('settings', setting.name),
                     ('started', now.strftime('%Y-%m-%d %H:%M'))] + details)


def _run_one(setting, now):
    """
    The weekly run of one settings. Returns the error message, None on
    success.
    """
    details = []
    try:
        version = _check_dependency(setting, now)
    except SkipRun as exp:
        CheckmkSettings.objects(id=setting.id).update_one(set__schedule_last_run=now)
        message = f"Skipped: {exp}"
        _finish(setting, now, 'skipped', message, details)
        return message
    if version:
        details.append(('depends_on', setting.schedule_depends_on.name))
    majors = None
    if setting.schedule_update_version and not version:
        try:
            majors = download_catalog.fetch(setting.download_proxy)
        except (requests.exceptions.RequestException, ValueError) as exp:
            # Not marked as done: the next cron pass of the day tries again
            message = f"Could not load the versions from checkmk.com, " \
                      f"tried again on the next pass: {exp}"
            _finish(setting, now, 'failure', message, details)
            return message
    CheckmkSettings.objects(id=setting.id).update_one(set__schedule_last_run=now)
    try:
        if setting.schedule_update_version:
            if version:
                _set_version(setting, _version_of_dependency(setting, version),
                             details)
            else:
                _set_version(setting, download_catalog.newest_patch(
                    majors, setting.cmk_version), details)
        if setting.schedule_run_playbook:
            _run_playbook(setting, details)
    except (ValueError, RuntimeError) as exp:
        _finish(setting, now, 'failure', str(exp), details)
        return str(exp)
    _finish(setting, now, 'success', 'Done', details)
    return None


def run_scheduled_updates(account=None, debug=False):  # pylint: disable=unused-argument
    """
    Cron job: the weekly runs of all enabled settings that are due now,
    the settings others depend on first
    """
    now = datetime.now()
    due = []
    for setting in CheckmkSettings.objects(enabled__ne=False).order_by('name'):
        if is_due(setting, now):
            try:
                due.append((len(dependency_chain(setting)), setting))
            except ValueError as exp:
                due.append((0, setting))
                print(f"{CC.FAIL} *{CC.ENDC} {exp}")
    errors = []
    for _, setting in sorted(due, key=lambda entry: entry[0]):
        print(f"\n{CC.HEADER}Weekly run of {setting.name}{CC.ENDC}")
        if (error := _run_one(setting, now)) is not None:
            errors.append(f"{setting.name}: {error}")
    if errors:
        task_failed(RuntimeError('; '.join(errors)))
