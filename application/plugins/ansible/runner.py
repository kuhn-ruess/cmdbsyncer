"""
Background runner for `ansible-playbook` invocations.

Used by the UI Run-button (subtask 1), the run_playbook rule outcome
(subtask 4), and the existing CLI. Each invocation is recorded as an
AnsibleRunStats row so users can see what ran, when, and inspect the
captured log.
"""
import os
import shlex
import subprocess
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import yaml

from application import app, logger
from .models import AnsibleRunStats

MANIFEST_FILENAME = 'playbooks.yml'
LOCAL_MANIFEST_FILENAME = 'playbooks.local.yml'


def _ansible_dir() -> Path:
    """
    Directory containing playbooks and the inventory script. Resolution
    order: explicit config override → `<repo>/ansible/`.
    """
    override = app.config.get('ANSIBLE_DIR') or os.environ.get('CMDBSYNCER_ANSIBLE_DIR')
    if override:
        return Path(override)
    return Path(app.root_path).parent / 'ansible'


def _ansible_binary() -> str:
    """Path to `ansible-playbook` (default: rely on $PATH)."""
    return app.config.get('ANSIBLE_PLAYBOOK_BIN') \
        or os.environ.get('CMDBSYNCER_ANSIBLE_PLAYBOOK_BIN') \
        or 'ansible-playbook'


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


def available_playbooks() -> "OrderedDict[str, str]":
    """
    Return an ordered mapping of playbook filename → friendly display name,
    sourced from `playbooks.yml` (bundled) merged with `playbooks.local.yml`
    (user-managed, gitignored). Local entries override bundled entries by
    `file`; new local entries append to the end.

    Entries that point to a non-existent file are dropped — the UI should
    not offer to run a playbook that disappeared from disk.
    """
    base = _ansible_dir()
    if not base.is_dir():
        return OrderedDict()

    catalog: "OrderedDict[str, str]" = OrderedDict()
    for manifest in (MANIFEST_FILENAME, LOCAL_MANIFEST_FILENAME):
        for entry in _load_manifest(base / manifest):
            if not isinstance(entry, dict):
                continue
            file_name = (entry.get('file') or '').strip()
            display = (entry.get('name') or file_name).strip()
            if not file_name:
                continue
            if not (base / file_name).is_file():
                logger.warning(
                    "Manifest entry references missing file: %s",
                    base / file_name,
                )
                continue
            catalog[file_name] = display
    return catalog


def _build_command(playbook: str, target_host: str | None,
                   extra_vars: str | None) -> list[str]:
    """Assemble the ansible-playbook argv."""
    base = _ansible_dir()
    cmd = [_ansible_binary(), '-i', str(base / 'inventory'), str(base / playbook)]
    if target_host:
        cmd += ['--limit', target_host]
    if extra_vars:
        cmd += ['-e', extra_vars]
    return cmd


def _execute(stats_id, cmd: list[str], cwd: Path):
    """
    Run ansible-playbook to completion and update the stats row. Stdout
    and stderr are interleaved so the log reads in chronological order.
    """
    with app.app_context():
        stats = AnsibleRunStats.objects(pk=stats_id).first()
        if not stats:
            return
        try:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            stats.pid = proc.pid
            stats.save()
            output, _ = proc.communicate()
            stats.log = output or ''
            stats.exit_code = proc.returncode
            stats.status = 'success' if proc.returncode == 0 else 'failure'
        except FileNotFoundError as exc:
            stats.log = f"ansible-playbook not found: {exc}"
            stats.exit_code = -1
            stats.status = 'failure'
        except Exception as exc:  # pylint: disable=broad-except
            stats.log = f"Runner error: {exc}\nCommand: {shlex.join(cmd)}"
            stats.exit_code = -1
            stats.status = 'failure'
        finally:
            stats.ended_at = datetime.now()
            stats.save()


def run_playbook(playbook: str, *,
                 target_host: str | None = None,
                 extra_vars: str | None = None,
                 source: str = 'ui',
                 triggered_by: str | None = None) -> AnsibleRunStats:
    """
    Kick off a playbook run in a background daemon thread and return the
    AnsibleRunStats record so callers can redirect to its detail page.

    Caller responsibility: validate `playbook` against available_playbooks()
    before invoking — this function does no whitelist check, so passing
    untrusted input would let users run arbitrary YAML files in the ansible
    directory.
    """
    base = _ansible_dir()
    stats = AnsibleRunStats(
        playbook=playbook,
        target_host=target_host or None,
        extra_vars=extra_vars or None,
        source=source,
        triggered_by=triggered_by,
        started_at=datetime.now(),
        status='running',
    )
    stats.save()

    cmd = _build_command(playbook, target_host, extra_vars)
    thread = threading.Thread(
        target=_execute,
        args=(stats.pk, cmd, base),
        daemon=True,
        name=f'ansible-runner-{stats.pk}',
    )
    thread.start()
    return stats
