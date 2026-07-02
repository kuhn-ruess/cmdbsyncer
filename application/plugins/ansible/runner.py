"""
Background runner for `ansible-playbook` invocations.

Used by the UI Run-button (subtask 1), the run_playbook rule outcome
(subtask 4), and the existing CLI. Each invocation is recorded as an
AnsibleRunStats row so users can see what ran, when, and inspect the
captured log.
"""
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import yaml

from application import app, logger
from .models import AnsibleRunStats

MANIFEST_FILENAME = 'playbooks.yml'
LOCAL_MANIFEST_FILENAME = 'playbooks.local.yml'
INVENTORY_SPEC_FILENAME = 'syncer.inventory.yml'
DEFAULT_PROVIDER = 'ansible'


def _ansible_dir() -> Path:
    """
    Directory containing playbooks and the inventory script. Resolution
    order:
      1. explicit config override (`ANSIBLE_DIR` / `CMDBSYNCER_ANSIBLE_DIR`)
      2. `<dirname(sys.prefix)>/ansible/` — pip-install convention where
         the venv lives inside the deployment dir
         (e.g. `/opt/cmdbsyncer/venv` → `/opt/cmdbsyncer/ansible`)
      3. `<repo>/ansible/` — source-checkout fallback, derived from the
         `application` package location

    The first existing directory wins. Pip-install layouts previously
    fell straight through to `Path(app.root_path).parent / 'ansible'`,
    which resolves to `<site-packages>/ansible/` — that directory doesn't
    exist on a normal install, so the runner reported "No playbooks
    declared" pointing at the wrong path.
    """
    override = app.config.get('ANSIBLE_DIR') or os.environ.get('CMDBSYNCER_ANSIBLE_DIR')
    if override:
        return Path(override)
    deploy_root = Path(sys.prefix).parent / 'ansible'
    if deploy_root.is_dir():
        return deploy_root
    return Path(app.root_path).parent / 'ansible'


def _ansible_binary() -> str:
    """Path to `ansible-playbook` (default: rely on $PATH)."""
    return app.config.get('ANSIBLE_PLAYBOOK_BIN') \
        or os.environ.get('CMDBSYNCER_ANSIBLE_PLAYBOOK_BIN') \
        or 'ansible-playbook'


def _inventory_plugin_dir() -> str | None:
    """
    Directory that holds the `cmdbsyncer_inventory` Ansible inventory
    plugin, so we can put it on ANSIBLE_INVENTORY_PLUGINS for the run.

    The plugin ships in the `cmdbsyncer_inventory` pip package (the
    `[ansible]` extra). Ansible only discovers inventory plugins on its
    configured plugin path, so without this the spec fails to parse with
    "unknown plugin 'cmdbsyncer_inventory'" — which is why UI runs never
    produced an inventory while the CLI (a direct `cmdbsyncer ansible
    inventory` call that bypasses Ansible plugin loading) worked. Returns
    None when the package isn't installed.
    """
    try:
        import cmdbsyncer_inventory  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    plugin_dir = os.path.join(
        os.path.dirname(cmdbsyncer_inventory.__file__), 'inventory_plugins',
    )
    return plugin_dir if os.path.isdir(plugin_dir) else None


def _cmdbsyncer_bin() -> str:
    """
    Resolve the `cmdbsyncer` CLI the inventory plugin shells in local mode.

    The plugin defaults to a bare `cmdbsyncer` and only looks on $PATH,
    which fails when the app runs from a source checkout / container where
    no `cmdbsyncer` console script is on PATH. Prefer an explicit config /
    env override, then PATH, then the repo-root wrapper that sits next to
    the `application` package (mirrors the legacy `ansible/inventory` shim).
    """
    override = app.config.get('CMDBSYNCER_BIN') or os.environ.get('CMDBSYNCER_BIN')
    if override:
        return override
    on_path = shutil.which('cmdbsyncer')
    if on_path:
        return on_path
    wrapper = Path(app.root_path).parent / 'cmdbsyncer'
    if wrapper.is_file():
        return str(wrapper)
    return 'cmdbsyncer'


def _load_manifest(path: Path) -> list[dict]:
    """Read and validate one manifest file. Missing file → empty list."""
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as exc:
        logger.warning("Skipping invalid playbook manifest %s: %s", path, exc)
        return []
    entries = data.get('playbooks') or []
    if not isinstance(entries, list):
        logger.warning("Manifest %s: 'playbooks' must be a list, ignoring", path)
        return []
    return entries


def _manifest_entries() -> "OrderedDict[str, dict]":
    """
    Merged manifest as `OrderedDict[filename, {'name', 'inventory'}]`.
    Local manifest entries override bundled entries by filename. Entries
    pointing at missing files are dropped.
    """
    base = _ansible_dir()
    if not base.is_dir():
        return OrderedDict()
    catalog: "OrderedDict[str, dict]" = OrderedDict()
    for manifest in (MANIFEST_FILENAME, LOCAL_MANIFEST_FILENAME):
        for entry in _load_manifest(base / manifest):
            if not isinstance(entry, dict):
                continue
            file_name = (entry.get('file') or '').strip()
            if not file_name:
                continue
            if not (base / file_name).is_file():
                logger.warning(
                    "Manifest entry references missing file: %s",
                    base / file_name,
                )
                continue
            catalog[file_name] = {
                'name': (entry.get('name') or file_name).strip(),
                'inventory': (entry.get('inventory') or DEFAULT_PROVIDER).strip(),
            }
    return catalog


def available_playbooks() -> "OrderedDict[str, str]":
    """
    Return an ordered mapping of playbook filename → friendly display name,
    sourced from `playbooks.yml` (bundled) merged with `playbooks.local.yml`
    (user-managed, gitignored). Local entries override bundled entries by
    `file`; new local entries append to the end.
    """
    return OrderedDict((f, e['name']) for f, e in _manifest_entries().items())


def playbook_inventory_provider(playbook: str) -> str:
    """
    Return the inventory provider declared for `playbook` in the manifest,
    falling back to the default provider when no entry exists. Used by the
    runner to set CMDBSYNCER_INVENTORY_PROVIDER when invoking the
    cmdbsyncer-inventory plugin.
    """
    entry = _manifest_entries().get(playbook)
    if entry is None:
        return DEFAULT_PROVIDER
    return entry['inventory']


def _build_command(inventory_path: str, run_params: dict,
                   vars_file: str | None = None) -> list[str]:
    """
    Assemble the ansible-playbook argv against `inventory_path` — a
    per-run cmdbsyncer-inventory spec that pins the provider for this run
    (written by `_execute`). Using a per-run spec rather than the shared
    `syncer.inventory.yml` guarantees the plugin serves the provider the
    caller selected: the plugin reads the spec's `provider:` option, and
    a shared spec with a pinned provider would otherwise ignore the
    CMDBSYNCER_INVENTORY_PROVIDER env var.

    The SSH user maps to `--user`, but only when no `vars_file` is given —
    with a password the user goes into that file too. `vars_file` is added
    as `-e @<file>` and carries the SSH login credentials, kept in a file
    rather than on the argv so the password never shows up in `ps` output.
    """
    base = _ansible_dir()
    cmd = [
        _ansible_binary(),
        '-i', inventory_path,
        str(base / run_params['playbook']),
    ]
    if run_params['check_mode']:
        cmd += ['--check', '--diff']
    if run_params['target_host']:
        cmd += ['--limit', run_params['target_host']]
    if not vars_file and run_params.get('ssh_user'):
        cmd += ['--user', run_params['ssh_user']]
    if run_params['extra_vars']:
        cmd += ['-e', run_params['extra_vars']]
    if vars_file:
        cmd += ['-e', f'@{vars_file}']
    return cmd


def _write_credentials_file(directory: str, ssh_user: str | None,
                            ssh_password: str) -> str:
    """
    Write the SSH login credentials as an ansible vars file (mode 0600) in
    the run's temp dir and return its path. Passing the password via a file
    (`-e @file`) instead of the command line keeps it out of the process
    list; `ansible_ssh_pass` needs `sshpass` installed on the host.
    """
    data = {'ansible_ssh_pass': ssh_password}
    if ssh_user:
        data['ansible_user'] = ssh_user
    path = os.path.join(directory, 'credentials.yml')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file_handle:
        yaml.safe_dump(data, file_handle, default_flow_style=False)
    return path


def _write_run_inventory_spec(directory: str, provider: str, mode: str,
                              cmdbsyncer_bin: str | None = None) -> str:
    """
    Write a per-run cmdbsyncer-inventory spec into `directory` and return
    its path. Keeping the canonical basename means the plugin's file
    verification behaves exactly as for the shared spec; only the
    `provider` (and, in local mode, the `cmdbsyncer_bin`) differ per run.
    """
    spec = {
        'plugin': 'cmdbsyncer_inventory',
        'mode': mode,
        'provider': provider,
    }
    # In local mode the plugin shells the cmdbsyncer CLI; pin its path so
    # it resolves even when no `cmdbsyncer` console script is on PATH.
    if mode == 'local' and cmdbsyncer_bin:
        spec['cmdbsyncer_bin'] = cmdbsyncer_bin
    spec_path = os.path.join(directory, INVENTORY_SPEC_FILENAME)
    with open(spec_path, 'w', encoding='utf-8') as file_handle:
        yaml.safe_dump(spec, file_handle, default_flow_style=False)
    return spec_path


def cancel_run(stats) -> bool:
    """
    Stop a still-running playbook by signalling its process group.

    The run started ansible-playbook in its own session (see `_execute`),
    so SIGTERM to the group stops ansible-playbook and its children without
    affecting the web worker. The `_execute` thread then observes the exit
    and records the run as 'cancelled'. Returns True if a signal was sent,
    False when there is nothing to cancel (no pid / already finished /
    process already gone).
    """
    if stats.status != 'running' or not stats.pid:
        return False
    try:
        os.killpg(os.getpgid(stats.pid), signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _stream_output(proc, stats) -> str:
    """
    Read the process output line by line and persist it into `stats.log`
    at a throttled cadence, so the auto-refreshing run detail page shows
    progress while the run is still 'running' instead of an empty log
    until it finishes. Returns the full captured log.
    """
    captured = []
    last_flush = time.monotonic()
    for line in proc.stdout:
        captured.append(line)
        now = time.monotonic()
        if now - last_flush >= 1.5:
            stats.log = ''.join(captured)
            stats.save()
            last_flush = now
    proc.wait()
    return ''.join(captured)


def _execute(stats_id, run_params: dict, cwd: Path, provider: str):
    """
    Run ansible-playbook to completion and update the stats row. Stdout
    and stderr are interleaved so the log reads in chronological order.

    The per-run inventory spec is written into the run's temp dir so the
    playbook is served by exactly the provider `provider` names.
    """
    with app.app_context():
        stats = AnsibleRunStats.objects(pk=stats_id).first()
        if not stats:
            return
        env = os.environ.copy()
        env['CMDBSYNCER_INVENTORY_PROVIDER'] = provider
        env.setdefault('CMDBSYNCER_INVENTORY_MODE', 'local')
        # A failed inventory parse (broken/outdated inventory plugin, bad
        # provider) otherwise leaves ansible-playbook running against an
        # empty host list and exiting 0 — which we would record as a
        # successful run. Make an unparsable inventory a fatal error so the
        # process exits non-zero and the run is logged as a failure.
        env.setdefault('ANSIBLE_INVENTORY_ANY_UNPARSED_IS_FAILED', 'True')
        # In local mode the plugin shells the cmdbsyncer CLI, which resolves
        # its config from $CMDBSYNCER_CONFIG_DIR / cwd. Point it at the
        # deployment root (where local_config.py sits, next to ansible/) so
        # the sub-process finds the same config as the web app — mirrors the
        # legacy ansible/inventory shim.
        env.setdefault('CMDBSYNCER_CONFIG_DIR', str(cwd.parent))
        # Make Ansible find the cmdbsyncer_inventory plugin regardless of
        # where the spec file lives (the run temp dir), prepending it to any
        # path the operator already configured.
        plugin_dir = _inventory_plugin_dir()
        if plugin_dir:
            configured = env.get('ANSIBLE_INVENTORY_PLUGINS')
            env['ANSIBLE_INVENTORY_PLUGINS'] = (
                f"{plugin_dir}{os.pathsep}{configured}" if configured else plugin_dir
            )
        # Ansible writes scratch files under ``$HOME/.ansible/tmp`` and
        # respects ``ANSIBLE_LOCAL_TEMP`` for the same path. Under mod_wsgi
        # / gunicorn the process inherits the web user's $HOME (e.g.
        # ``/usr/share/httpd/`` on RHEL Apache), which is not writable and
        # makes every playbook abort with "Unable to create local
        # directories(/usr/share/httpd/.ansible/tmp): Permission denied".
        # Give each run its own temp dir, point both vars at it, and
        # clean up afterwards so we don't leak under /tmp.
        run_tmp = tempfile.mkdtemp(prefix='cmdbsyncer-ansible-')
        env['ANSIBLE_LOCAL_TEMP'] = run_tmp
        env['HOME'] = run_tmp
        inventory_path = _write_run_inventory_spec(
            run_tmp, provider, env['CMDBSYNCER_INVENTORY_MODE'],
            cmdbsyncer_bin=_cmdbsyncer_bin(),
        )
        vars_file = None
        if run_params.get('ssh_password'):
            vars_file = _write_credentials_file(
                run_tmp, run_params.get('ssh_user'), run_params['ssh_password'],
            )
        cmd = _build_command(inventory_path, run_params, vars_file=vars_file)
        try:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                # Own process group/session so a cancel can signal the whole
                # ansible-playbook process tree without touching the web
                # worker (see cancel_run()).
                start_new_session=True,
            )
            stats.pid = proc.pid
            stats.save()
            stats.log = _stream_output(proc, stats)
            stats.exit_code = proc.returncode
            # A negative return code means the process was killed by a signal
            # — that is how cancel_run() stops a run, so report it as
            # 'cancelled' rather than a generic failure.
            if proc.returncode == 0:
                stats.status = 'success'
            elif proc.returncode < 0:
                stats.status = 'cancelled'
            else:
                stats.status = 'failure'
        except FileNotFoundError as exc:
            stats.log = f"ansible-playbook not found: {exc}"
            stats.exit_code = -1
            stats.status = 'failure'
        except Exception as exc:  # pylint: disable=broad-except
            stats.log = f"Runner error: {exc}\nCommand: {shlex.join(cmd)}"
            stats.exit_code = -1
            stats.status = 'failure'
        finally:
            shutil.rmtree(run_tmp, ignore_errors=True)
            stats.ended_at = datetime.now()
            stats.save()


def run_playbook(playbook: str, *,  # pylint: disable=too-many-arguments
                 target_host: str | None = None,
                 extra_vars: str | None = None,
                 check_mode: bool = False,
                 provider: str | None = None,
                 ssh_user: str | None = None,
                 ssh_password: str | None = None,
                 source: str = 'ui',
                 triggered_by: str | None = None) -> AnsibleRunStats:
    """
    Kick off a playbook run in a background daemon thread and return the
    AnsibleRunStats record so callers can redirect to its detail page.
    With `check_mode=True` the playbook runs as `--check --diff` (no
    changes applied; diff rendered into the log). `provider` overrides
    the manifest's `inventory:` field for this run; pass None to use the
    manifest default.

    `ssh_user` / `ssh_password` set the SSH login for the connection.
    The password is written to a mode-0600 vars file for the run (never
    the command line) and is not stored on the run record; password auth
    needs `sshpass` on the host.

    Caller responsibility: validate `playbook` against available_playbooks()
    before invoking — this function does no whitelist check, so passing
    untrusted input would let users run arbitrary YAML files in the ansible
    directory.
    """
    base = _ansible_dir()
    if not provider:
        provider = playbook_inventory_provider(playbook)
    stats = AnsibleRunStats(
        playbook=playbook,
        target_host=target_host or None,
        extra_vars=extra_vars or None,
        mode='check' if check_mode else 'run',
        source=source,
        triggered_by=triggered_by,
        started_at=datetime.now(),
        status='running',
    )
    stats.save()

    run_params = {
        'playbook': playbook,
        'target_host': target_host,
        'extra_vars': extra_vars,
        'check_mode': check_mode,
        'ssh_user': ssh_user,
        'ssh_password': ssh_password,
    }
    thread = threading.Thread(
        target=_execute,
        args=(stats.pk, run_params, base, provider),
        daemon=True,
        name=f'ansible-runner-{stats.pk}',
    )
    thread.start()
    return stats
