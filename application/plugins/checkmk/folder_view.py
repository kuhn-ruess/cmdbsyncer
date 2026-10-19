"""
Checkmk folders as the host export computes them, read only.

The host export puts every host into a folder (Move to Folder, Pool Folder,
...) and collects the folder options behind a ``|`` (contact groups, title,
tags, ...) of every host that lands in a folder into one set of folder
attributes (see ``SyncCMK2.handle_extra_folder_options``). This module runs
the same rules for the Checkmk Folders page, without Checkmk: no request is
sent, no pool seat is taken or freed, no host and no cache is saved.

For the debug of one folder it also tells which host and which Export Rule
gave which value, and what the merge made of it.
"""
import contextlib
import io

from application.modules.rule.rule import format_condition
from .rules import folder_options_tree
from .syncer import drop_unset_folder_values, merge_folder_attributes

# Outcome keys holding a folder path with its ``|{options}``, and the kind
# of folder they stand for.
OPTION_SOURCES = (
    ('extra_folder_options', 'move'),
    ('create_folder_extra_folder_options', 'create'),
)

# Export Rule actions that put a folder into the outcome.
FOLDER_ACTIONS = ('move_folder', 'create_folder', 'folder_pool',
                  'value_as_folder', 'tag_as_folder')


def folder_prefixes(path):
    """``/a/b`` -> ``['/a', '/a/b']``; the main folder has none."""
    prefixes = []
    current = ''
    for part in (path or '').split('/'):
        if part:
            current += '/' + part
            prefixes.append(current)
    return prefixes


def _new_folder(path):
    return {'path': path, 'hosts': [], 'contributions': [],
            'attributes': None, 'trace': []}


def host_contributions(hostname, actions):
    """
    The folder options one host hands to the export, one entry per folder
    level that carries options (or broken ones), in the order the export
    reads them.
    """
    found = []
    for key, kind in OPTION_SOURCES:
        source = actions.get(key) or ''
        if '{' not in source:
            # The export only parses values with a dict in them.
            continue
        for index, level in enumerate(folder_options_tree(source)):
            if not level['attributes'] and not level['error']:
                continue
            attributes, dropped = level['attributes'], []
            if not level['error']:
                attributes, dropped = drop_unset_folder_values(
                    level['path'], level['attributes'])
            found.append({
                'folder': level['path'],
                'hostname': hostname,
                'kind': kind,
                'level': index,
                'attributes': attributes,
                'dropped': dropped,
                'error': level['error'],
                'rule': None,
            })
    return found


def _trace_values(existing, new, prefix, notes):
    """What ``merge_folder_attributes(existing, new)`` does, per value."""
    for key, value in new.items():
        path = f"{prefix}{key}"
        if key not in existing:
            if isinstance(value, dict) and value:
                # Name every value of a new dict, e.g. contactgroups.groups.
                _trace_values({}, value, path + '.', notes)
            else:
                notes.append({'path': path, 'effect': 'set', 'value': value})
            continue
        current = existing[key]
        if isinstance(current, dict) and isinstance(value, dict):
            _trace_values(current, value, path + '.', notes)
        elif isinstance(current, list) and isinstance(value, list):
            added = [x for x in value if x not in current]
            present = [x for x in value if x in current]
            if added:
                notes.append({'path': path, 'effect': 'added', 'value': added})
            if present:
                notes.append({'path': path, 'effect': 'present',
                              'value': present})
        elif current == value:
            notes.append({'path': path, 'effect': 'same', 'value': value})
        else:
            notes.append({'path': path, 'effect': 'ignored', 'value': value,
                          'kept': current})


def merge_trace(contributions):
    """
    Merge the folder options of ``contributions`` the way the export does
    (first one as is, every following one through
    ``merge_folder_attributes``) and note per contribution what happened
    to each of its values: ``set`` (new), ``added`` (list entries new to
    the list), ``present`` (list entries already there), ``same`` (equal
    value already there) or ``ignored`` (another value came first, it
    stays).

    Returns ``(attributes, notes)``: the final attributes (None when no
    contribution parsed) and one list of notes per contribution.
    """
    merged = None
    all_notes = []
    for entry in contributions:
        notes = []
        value = entry['attributes']
        if entry['error']:
            notes.append({'path': '', 'effect': 'broken', 'value': entry['error']})
        elif merged is None:
            if isinstance(value, dict):
                _trace_values({}, value, '', notes)
            else:
                notes.append({'path': '', 'effect': 'set', 'value': value})
            merged = value
        elif isinstance(merged, dict) and isinstance(value, dict):
            _trace_values(merged, value, '', notes)
            merged = merge_folder_attributes(merged, value)
        else:
            notes.append({'path': '', 'effect': 'ignored', 'value': value,
                          'kept': merged})
        for name in entry.get('dropped') or []:
            notes.append({'path': name, 'effect': 'dropped', 'value': None})
        all_notes.append(notes)
    return merged, all_notes


def build_folders(host_results):
    """
    The folders the export would know about from ``host_results`` (a list
    of ``(hostname, actions)`` of the exported hosts, in export order):
    ``{path: folder}`` with the hosts that land directly in the folder,
    every folder option contribution and the merged attributes.
    """
    folders = {'/': _new_folder('/')}
    for hostname, actions in host_results:
        target = actions.get('move_folder') or '/'
        for path in folder_prefixes(target) + \
                folder_prefixes(actions.get('create_folder') or ''):
            folders.setdefault(path, _new_folder(path))
        folders[target]['hosts'].append(hostname)
        for entry in host_contributions(hostname, actions):
            folders.setdefault(entry['folder'], _new_folder(entry['folder']))
            folders[entry['folder']]['contributions'].append(entry)
    for folder in folders.values():
        folder['attributes'], folder['trace'] = \
            merge_trace(folder['contributions'])
    return folders


def subtree_hosts(folders, path):
    """Every host of the folder ``path`` and of its sub-folders."""
    if path == '/':
        return [h for folder in folders.values() for h in folder['hosts']]
    return [h for key, folder in folders.items()
            if key == path or key.startswith(path + '/')
            for h in folder['hosts']]


def scope_folders(folders, visible):
    """
    The folders as a user with a host scope may see them. ``visible`` is
    the set of hostnames the user may see, None for an unrestricted user
    (everything is returned unchanged).

    A folder stays when one of its visible hosts sits in it or below it,
    or a visible host gives it options. Hosts and contributions of other
    hosts are left out, and the attributes are merged from the visible
    contributions only: the value of a shared folder must not tell a
    restricted user the contact groups of hosts they may not see. The
    folder counts what was left out, so the page can say so.
    """
    if visible is None:
        return folders
    keep = set()
    for path, folder in folders.items():
        if any(h in visible for h in folder['hosts']) or \
                any(c['hostname'] in visible for c in folder['contributions']):
            keep.add(path)
            keep.update(folder_prefixes(path))
            keep.add('/')
    scoped = {}
    for path, folder in folders.items():
        if path not in keep:
            continue
        hosts = [h for h in folder['hosts'] if h in visible]
        contributions = [c for c in folder['contributions']
                         if c['hostname'] in visible]
        attributes, trace = merge_trace(contributions)
        scoped[path] = dict(
            folder, hosts=hosts, contributions=contributions,
            attributes=attributes, trace=trace,
            hidden_hosts=len(folder['hosts']) - len(hosts),
            hidden_contributions=len(folder['contributions']) - len(contributions))
    return scoped


def rule_owners(debug_lines):
    """
    Which Export Rule put which folder level into the outcome:
    ``{(kind, level index): debug line}``. Every rule appends its folder
    to the outcome, so the levels a rule adds are the ones the value has
    after it and did not have before.
    """
    owners = {}
    previous = {key: '' for key, _ in OPTION_SOURCES}
    for line in debug_lines:
        if not line.get('hit'):
            continue
        outcome = line.get('outcome') or {}
        for key, kind in OPTION_SOURCES:
            value = outcome.get(key)
            if value is None or value == previous[key]:
                continue
            before = len(folder_options_tree(previous[key]))
            for index in range(before, len(folder_options_tree(value))):
                owners[(kind, index)] = line
            previous[key] = value
    return owners


def _rule_info(line, params):
    return {
        'id': line.get('id'),
        'name': line.get('name'),
        'condition_type': line.get('condition_type'),
        'conditions': [format_condition(c) for c in line.get('match_reasons') or []],
        'params': params.get(line.get('id'), []),
    }


def _folder_params():
    """Rule id -> the folder actions of every enabled Export Rule."""
    from .models import CheckmkRule as CheckmkRuleModel  # pylint: disable=import-outside-toplevel
    params = {}
    for rule in CheckmkRuleModel.objects(enabled=True).only('outcomes'):
        params[str(rule.id)] = [
            {'action': outcome.action, 'param': outcome.action_param or ''}
            for outcome in rule.outcomes or [] if outcome.action in FOLDER_ACTIONS]
    return params


class FolderCalculation:
    """
    Run the host export's rules over the hosts, offline and read only.

    ``account`` is the name of a Checkmk account: its host selection (object
    filter, limit by hostnames and accounts, Projects, folder scope) is
    applied as in its export. Without one every host is calculated, like
    on the host debug page.
    """

    def __init__(self, account=None):
        # pylint: disable=import-outside-toplevel
        from . import _load_rules
        from .rules import host_folder_engine
        from .syncer import SyncCMK2
        self.account = account or None
        # probe_version=False: the constructor asks Checkmk nothing.
        self.syncer = SyncCMK2(self.account or False, probe_version=False)
        rules = _load_rules()
        self.syncer.filter = rules['filter']
        self.syncer.rewrite = rules['rewrite']
        # Never takes or frees a pool seat (see host_folder_engine).
        self.syncer.actions = host_folder_engine()
        if self.account:
            # The name the export runs under, its object filter is keyed by it.
            self.syncer.name = f"Sync Hosts to Account: {self.syncer.account_name}"
        self.results = []

    def _hosts(self):
        from application.models.host import Host  # pylint: disable=import-outside-toplevel
        settings = (self.syncer.config or {}).get('settings') or {}
        object_filter = settings.get(self.syncer.name, {}).get('filter')
        return Host.objects_by_filter(object_filter)

    def _outcomes(self, db_host, attributes):
        return self.syncer.actions.get_outcomes(
            db_host, attributes['all'], persist_cache=False, use_cache=False)

    def run(self):
        """
        Calculate every host the export would send. Returns the list of
        ``(db_host, actions, attributes)``.
        """
        syncer = self.syncer
        self.results = []
        for db_host in self._hosts():
            if self.account and (
                    not syncer.use_host(db_host.hostname, db_host.source_account_name)
                    or syncer.project_denied_for_account(db_host.project)):
                continue
            # Calculate fresh, like the host debug page. Only the copy in
            # memory is emptied, the host is never saved.
            db_host.cache = {}
            attributes = syncer.get_attributes(db_host, False, persist_cache=False)
            if not attributes:
                continue
            actions = self._outcomes(db_host, attributes)
            # pylint: disable-next=protected-access
            if not syncer._host_result_exported(True, (actions, attributes),
                                                db_host.project):
                continue
            self.results.append((db_host, actions, attributes))
        return self.results

    def folders(self):
        """``build_folders`` of the calculated hosts."""
        return build_folders([(db_host.hostname, actions)
                              for db_host, actions, _ in self.results])

    def attribute_rules(self, folder):
        """
        Fill in ``rule`` of every contribution of ``folder`` (a folder of
        ``folders()``): the Export Rule that put the options there, with
        the conditions that made it match. Runs the rules once more with
        debug for the hosts that give the folder options.
        """
        wanted = {c['hostname'] for c in folder['contributions']}
        if not wanted:
            return folder
        engine = self.syncer.actions
        engine.debug = True
        params = _folder_params()
        owners_by_host = {}
        for db_host, _, attributes in self.results:
            if db_host.hostname not in wanted:
                continue
            engine.debug_lines = []
            # The debug run prints a table per host, not wanted in the log.
            with contextlib.redirect_stdout(io.StringIO()):
                self._outcomes(db_host, attributes)
            owners_by_host[db_host.hostname] = rule_owners(engine.debug_lines)
        engine.debug = False
        for entry in folder['contributions']:
            line = owners_by_host.get(entry['hostname'], {}).get(
                (entry['kind'], entry['level']))
            if line:
                entry['rule'] = _rule_info(line, params)
        return folder
