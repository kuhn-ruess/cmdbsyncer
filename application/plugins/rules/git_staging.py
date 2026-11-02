"""
Rule Staging over Git

Push the rules of selected types from one Syncer (e.g. test) into a Git
repository and pull them into another one (e.g. production). Every rule
type is one file ``<path>/<rule_type>.json`` holding its rules as a JSON
list sorted by id, so a Git diff shows exactly which rules changed.

The repository is reached over HTTPS with the user and token of an
account of type ``git``. The token travels in an HTTP header passed
through the environment — it is neither written into the clone's
``.git/config`` nor visible on the command line.
"""
import base64
import json
import os
import subprocess
import tempfile

from application import log
from application.helpers.get_account import get_account_by_name, AccountNotFoundError

from .rule_definitions import rules as enabled_rules
from .rule_import_export import (
    ACCOUNTS_RULE_TYPE,
    HOST_COLLECTION_RULE_TYPE,
    PASSWORDS_RULE_TYPE,
    USERS_RULE_TYPE,
    _model_class_for,
    _queryset_filter_for,
    import_rule_lines,
    iter_rules_of_type,
)

ACCOUNT_TYPE = 'git'
GIT_TIMEOUT = 300

# Types that differ by nature between two instances: hosts come from the
# imports, accounts point at each instance's own systems, users are local
# and the Secret Store is encrypted with each instance's own key.
EXCLUDED_RULE_TYPES = {
    HOST_COLLECTION_RULE_TYPE,
    ACCOUNTS_RULE_TYPE,
    USERS_RULE_TYPE,
    PASSWORDS_RULE_TYPE,
}


class GitStagingError(Exception):
    """Push or pull could not be done."""


def staging_rule_types():
    """Rule types which can be moved through Git, sorted."""
    return sorted(set(enabled_rules) - EXCLUDED_RULE_TYPES)


def _check_rule_types(rule_types):
    """Return *rule_types* as a sorted list, raise on unknown ones."""
    unknown = set(rule_types) - set(staging_rule_types())
    if unknown:
        raise GitStagingError(
            f"Rule type(s) not supported for Git: {', '.join(sorted(unknown))}")
    return sorted(set(rule_types))


def _repo_path(value):
    """The folder inside the repository, without leading/trailing slashes."""
    path = (value or '').strip().strip('/')
    if '..' in path.split('/'):
        raise GitStagingError("The path must not contain '..'")
    return path


def repo_config(account_name):
    """Read the repository settings from the account *account_name*."""
    try:
        account = get_account_by_name(account_name)
    except AccountNotFoundError as error:
        raise GitStagingError(f"Account '{account_name}' not found") from error
    if account.get('typ') != ACCOUNT_TYPE:
        raise GitStagingError(
            f"Account '{account_name}' is not of type Git Repository")
    if not account.get('address'):
        raise GitStagingError(f"Account '{account_name}' has no address")
    return {
        'url': account['address'],
        'username': account.get('username') or '',
        'password': account.get('password') or '',
        'branch': account.get('branch') or 'main',
        'path': _repo_path(account.get('path')),
        'rule_types': account.get('rule_types') or '',
        'delete_missing': account.get('delete_missing') is True,
        'verify_cert': account.get('verify_cert') is not False,
    }


def _git(config, *args, cwd=None):
    """Run one git command for the repository of *config*, return stdout."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    if config['username'] or config['password']:
        credentials = f"{config['username']}:{config['password']}"
        token = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        env.update({
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'http.extraHeader',
            'GIT_CONFIG_VALUE_0': f'Authorization: Basic {token}',
        })
    command = ['git']
    if not config['verify_cert']:
        command += ['-c', 'http.sslVerify=false']
    command += list(args)
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=GIT_TIMEOUT, check=False)
    except FileNotFoundError as error:
        raise GitStagingError("git is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise GitStagingError(f"git {args[0]} timed out") from error
    if result.returncode != 0:
        raise GitStagingError(
            f"git {args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def _checkout(config, workdir, create_missing):
    """
    Clone the branch into *workdir*. A missing branch is started fresh
    with *create_missing*, otherwise it is an error.
    """
    heads = _git(config, 'ls-remote', '--heads', config['url'], config['branch'])
    if heads.strip():
        _git(config, 'clone', '--depth', '1', '--branch', config['branch'],
             config['url'], workdir)
        return
    if not create_missing:
        raise GitStagingError(
            f"Branch '{config['branch']}' not found in the repository")
    _git(config, 'init', '--initial-branch', config['branch'], workdir)
    _git(config, 'remote', 'add', 'origin', config['url'], cwd=workdir)


def _rule_sort_key(rule):
    """Sort rules by their id, so an unchanged rule never moves in the file."""
    rule_id = rule.get('_id')
    if isinstance(rule_id, dict):
        rule_id = rule_id.get('$oid')
    return str(rule_id or '')


def rule_file_content(rule_type):
    """The content of the repository file for *rule_type*."""
    rules = [json.loads(raw) for raw in iter_rules_of_type(rule_type)]
    rules.sort(key=_rule_sort_key)
    return json.dumps(rules, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def push_rules(account_name, rule_types, message='', author=None):
    """
    Write the rules of *rule_types* into the repository and push them.
    Files of other rule types in the repository stay as they are.
    *author* is a ``(name, email)`` tuple for the commit.

    Returns ``{'changed': [file, ...], 'commit': sha or None}``.
    """
    config = repo_config(account_name)
    rule_types = _check_rule_types(rule_types)
    if not rule_types:
        raise GitStagingError("No rule type selected")
    name, email = author or ('CMDBsyncer', 'cmdbsyncer@localhost')
    message = message.strip() or f"Rules: {', '.join(rule_types)}"

    with tempfile.TemporaryDirectory(prefix='syncer_rules_') as tmp:
        workdir = os.path.join(tmp, 'repo')
        _checkout(config, workdir, create_missing=True)
        folder = os.path.join(workdir, config['path'])
        os.makedirs(folder, exist_ok=True)
        for rule_type in rule_types:
            with open(os.path.join(folder, f"{rule_type}.json"), 'w',
                      encoding='utf-8') as rule_file:
                rule_file.write(rule_file_content(rule_type))
        _git(config, 'add', '--all', '--', config['path'] or '.', cwd=workdir)
        status = _git(config, 'status', '--porcelain', cwd=workdir)
        changed = [line[3:] for line in status.splitlines() if line.strip()]
        if not changed:
            return {'changed': [], 'commit': None}
        _git(config, '-c', f'user.name={name}', '-c', f'user.email={email}',
             'commit', '--quiet', '-m', message, cwd=workdir)
        _git(config, 'push', 'origin', f"HEAD:refs/heads/{config['branch']}",
             cwd=workdir)
        commit = _git(config, 'rev-parse', '--short', 'HEAD', cwd=workdir).strip()
    log.log(f"Rules pushed to Git: {account_name}", source="rules_git",
            details=[('commit', commit)] + [('file', x) for x in changed])
    return {'changed': changed, 'commit': commit}


def _rule_ids(rules):
    """The ids of the rules from a repository file."""
    ids = []
    for rule in rules:
        rule_id = rule.get('_id') if isinstance(rule, dict) else None
        if isinstance(rule_id, dict):
            rule_id = rule_id.get('$oid')
        if rule_id:
            ids.append(rule_id)
    return ids


def _delete_missing(rule_type, keep_ids):
    """Delete the rules of *rule_type* not in *keep_ids*, return the count."""
    model_class = _model_class_for(rule_type)
    queryset = model_class.objects(**_queryset_filter_for(rule_type)) \
        .filter(id__nin=keep_ids)
    count = queryset.count()
    queryset.delete()
    return count


def _load_type(folder, rule_type, delete_missing):
    """Import one rule type from its repository file."""
    with open(os.path.join(folder, f"{rule_type}.json"), encoding='utf-8') as rule_file:
        try:
            rules = json.load(rule_file)
        except json.JSONDecodeError as error:
            return {'error': f"Invalid JSON: {error}"}
    if not isinstance(rules, list):
        return {'error': "The file does not hold a list of rules"}
    result = {'total': len(rules), 'deleted': 0}
    try:
        if delete_missing:
            result['deleted'] = _delete_missing(rule_type, _rule_ids(rules))
        counts = import_rule_lines(rules, default_rule_type=rule_type, override=True)
    except Exception as error:  # pylint: disable=broad-exception-caught
        result['error'] = str(error)
        return result
    result['imported'] = counts.get(rule_type, 0)
    return result


def repo_rule_types(folder):
    """The supported rule types which have a file in *folder*."""
    if not os.path.isdir(folder):
        return []
    supported = set(staging_rule_types())
    return sorted(name[:-len('.json')] for name in os.listdir(folder)
                  if name.endswith('.json') and name[:-len('.json')] in supported)


def pull_rules(account_name, rule_types=None, delete_missing=False):
    """
    Import the rules from the repository. Rules from the repository
    replace existing rules with the same id or name. *rule_types* limits
    the import, empty takes every type found in the repository. With
    *delete_missing* rules of a pulled type which are not in the
    repository are deleted.

    Returns ``{'commit': sha, 'types': {rule_type: result}, 'missing': [...]}``
    where *missing* lists the requested types without a file.
    """
    config = repo_config(account_name)
    requested = _check_rule_types(rule_types or [])

    with tempfile.TemporaryDirectory(prefix='syncer_rules_') as tmp:
        workdir = os.path.join(tmp, 'repo')
        _checkout(config, workdir, create_missing=False)
        commit = _git(config, 'rev-parse', '--short', 'HEAD', cwd=workdir).strip()
        folder = os.path.join(workdir, config['path'])
        available = repo_rule_types(folder)
        selected = [x for x in requested if x in available] if requested else available
        results = {rule_type: _load_type(folder, rule_type, delete_missing)
                   for rule_type in selected}
    result = {
        'commit': commit,
        'types': results,
        'missing': [x for x in requested if x not in available],
    }
    log.log(f"Rules pulled from Git: {account_name}", source="rules_git",
            details=[('error' if ' — error: ' in line else 'info', line)
                     for line in format_pull_result(result)])
    return result


def split_rule_types(value):
    """Turn a comma separated list of rule types into a list."""
    return [x.strip() for x in (value or '').split(',') if x.strip()]


def format_pull_result(result):
    """Human readable lines describing the result of ``pull_rules``."""
    lines = [f"Commit {result['commit']}"]
    for rule_type, entry in sorted(result['types'].items()):
        line = (f"{rule_type}: {entry.get('imported', 0)} of "
                f"{entry.get('total', 0)} imported")
        if entry.get('deleted'):
            line += f", {entry['deleted']} deleted"
        if entry.get('error'):
            line += f" — error: {entry['error']}"
        lines.append(line)
    if result['missing']:
        lines.append(f"Not in the repository: {', '.join(result['missing'])}")
    return lines
