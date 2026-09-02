"""
Checkmk Data Quality checks.

Take a list of hostnames (typically uploaded as a CSV in the GUI) and check
them against a Checkmk account's monitoring data to answer three questions
operators regularly ask about their inventory:

* Is the host actually there (present in the monitoring)?
* Does its agent work (state of the ``Check_MK`` service)?
* Who is allowed to see it (the host's contact groups)?

The CSV parsing here is deliberately dependency-free and side-effect-free so it
can be unit tested without a Checkmk connection. The Checkmk request stack is
only pulled in by ``run_data_quality_check`` at call time.
"""
import csv
import io
import json
import re
from datetime import datetime

# Livestatus state code -> human label. Host and service states share the
# 0/1/2/3 encoding but mean different things, so keep two maps.
HOST_STATE_LABELS = {0: 'UP', 1: 'DOWN', 2: 'UNREACHABLE'}
SERVICE_STATE_LABELS = {0: 'OK', 1: 'WARN', 2: 'CRIT', 3: 'UNKNOWN'}

# Column headers that mark the hostname column when the CSV carries a header
# row. Matched case-insensitively against the trimmed header cells.
_HOSTNAME_HEADERS = ('hostname', 'host_name', 'host', 'name')

# Split pasted text on any run of newline / comma / semicolon / whitespace.
_TEXT_SPLIT = re.compile(r'[\s,;]+')


def parse_hostnames_from_text(text):
    """
    Extract a de-duplicated, order-preserving list of hostnames from free text
    pasted into a textarea. Splits on newlines, commas, semicolons and
    whitespace so both "one per line" and "a, b, c" pastes work.
    """
    if not text:
        return []
    hostnames = []
    seen = set()
    for token in _TEXT_SPLIT.split(text):
        name = token.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        hostnames.append(name)
    return hostnames


def _short_name(hostname):
    """Lowercased part before the first dot — the domain-agnostic key."""
    return hostname.split('.', 1)[0].lower()


def _short_name_index(names):
    """Index the given names by their short name for the domain-agnostic join."""
    index = {}
    for name in names:
        index.setdefault(_short_name(name), []).append(name)
    return index


def _resolve_name(hostname, names, short_index):
    """
    Find ``hostname`` in ``names``: an exact hit first, otherwise every name
    sharing its short part (the same host under a different domain).

    Returns ``(best_match, all_matches)``, both empty when nothing matches.
    """
    if hostname in names:
        return hostname, [hostname]
    matches = short_index.get(_short_name(hostname), [])
    if matches:
        return matches[0], matches
    return None, []


def parse_hostnames_from_csv(text):
    """
    Extract a de-duplicated, order-preserving list of hostnames from CSV text.

    The hostname column is picked as follows:

    * If the first row contains a cell like ``hostname`` / ``host`` / ``name``
      (case-insensitive), that column is used and the header row is skipped.
    * Otherwise the first column is used and no row is treated as a header.

    Empty cells and blank lines are ignored; surrounding whitespace is stripped.
    """
    if not text:
        return []

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any((cell or '').strip() for cell in row)]
    if not rows:
        return []

    column = 0
    start = 0
    header = [(cell or '').strip().lower() for cell in rows[0]]
    for candidate in _HOSTNAME_HEADERS:
        if candidate in header:
            column = header.index(candidate)
            start = 1
            break

    hostnames = []
    seen = set()
    for row in rows[start:]:
        if column >= len(row):
            continue
        name = (row[column] or '').strip()
        if not name or name in seen:
            continue
        seen.add(name)
        hostnames.append(name)
    return hostnames


def _fetch_monitored_hosts(cmk):
    """Map every monitored host to its state and contact groups (one API call)."""
    url = "domain-types/host/collections/all"
    params = {"columns": ['name', 'state', 'contact_groups']}
    data, _headers = cmk.request(url, method="GET", params=params)
    result = {}
    for row in data.get('value', []) or []:
        ext = row.get('extensions', {}) or {}
        name = ext.get('name') or row.get('id')
        if not name:
            continue
        result[name] = {
            'state': ext.get('state'),
            'contact_groups': ext.get('contact_groups') or [],
        }
    return result


def _fetch_checkmk_services(cmk):
    """Map every host to its ``Check_MK`` service state/output (one API call)."""
    url = "domain-types/service/collections/all"
    query = {"op": "=", "left": "description", "right": "Check_MK"}
    params = {
        "query": json.dumps(query),
        "columns": ['host_name', 'state', 'plugin_output'],
    }
    data, _headers = cmk.request(url, method="GET", params=params)
    result = {}
    for row in data.get('value', []) or []:
        ext = row.get('extensions', {}) or {}
        host_name = ext.get('host_name')
        if not host_name:
            continue
        result[host_name] = {
            'state': ext.get('state'),
            'output': ext.get('plugin_output') or '',
        }
    return result


def build_report(hostnames, monitored_hosts, checkmk_services):
    """
    Join the uploaded hostnames against the fetched monitoring data.

    Each host gets one of three states:

    * ``found`` — an exact name match exists in the monitoring.
    * ``domain_mismatch`` — no exact match, but a host with the same short name
      (part before the first dot) exists under a different name. This catches
      the "created with a different domain" / "given without a domain but
      monitored with one" cases the operator cares about; ``matched_names``
      lists the actual Checkmk name(s).
    * ``missing`` — neither an exact nor a short-name match exists.

    Pure function (no I/O) so the join logic is unit-testable. Returns a dict
    with a per-host ``results`` list and an aggregate ``summary``.
    """
    # Index the monitored hosts by short name so a domain mismatch is a cheap
    # dict lookup instead of an O(hosts) scan per uploaded host.
    short_index = _short_name_index(monitored_hosts)

    results = []
    summary = {
        'total': len(hostnames),
        'found': 0,
        'domain_mismatch': 0,
        'missing': 0,
        'agent_ok': 0,
        'agent_problem': 0,
        'no_agent': 0,
    }
    for hostname in hostnames:
        entry = {
            'hostname': hostname,
            'status': 'missing',
            'exists': False,
            'cmk_name': None,
            'matched_names': [],
            'host_state': None,
            'contact_groups': [],
            'agent_state': None,
            'agent_output': '',
        }
        match, matches = _resolve_name(hostname, monitored_hosts, short_index)
        if match == hostname:
            entry['status'] = 'found'
            entry['cmk_name'] = hostname
            summary['found'] += 1
        elif match:
            entry['status'] = 'domain_mismatch'
            entry['cmk_name'] = match
            entry['matched_names'] = matches
            summary['domain_mismatch'] += 1
        else:
            summary['missing'] += 1

        cmk_name = entry['cmk_name']
        if cmk_name is not None:
            entry['exists'] = True
            host = monitored_hosts[cmk_name]
            entry['host_state'] = HOST_STATE_LABELS.get(host['state'], host['state'])
            entry['contact_groups'] = host['contact_groups']
            service = checkmk_services.get(cmk_name)
            if service is None:
                summary['no_agent'] += 1
            else:
                state = service['state']
                entry['agent_state'] = SERVICE_STATE_LABELS.get(state, state)
                entry['agent_output'] = service['output']
                if state == 0:
                    summary['agent_ok'] += 1
                else:
                    summary['agent_problem'] += 1
        results.append(entry)
    return {'results': results, 'summary': summary}


def cmdb_candidates(report):
    """
    Pure: every name a report row could be stored under in the syncer's CMDB —
    the name that was given plus the name(s) the host carries in Checkmk.
    """
    names = set()
    for entry in report['results']:
        names.add(entry['hostname'])
        names.update(entry.get('matched_names') or [])
    return names


def attach_cmdb_info(report, cmdb_hosts):
    """
    Enrich every report row with the syncer's own CMDB state: under which name
    the host is known there (``cmdb_name``, ``None`` when it is not) and which
    CMDB templates it carries (``cmdb_templates``).

    ``cmdb_hosts`` maps a hostname to its list of template names. A row is
    matched by the name that was given first and by the Checkmk name(s) second,
    because the CMDB may know the host under either one.

    Pure function; mutates and returns the given report so the summary gains
    the ``in_cmdb`` / ``with_template`` / ``without_template`` counts.
    """
    summary = report['summary']
    summary.update({'in_cmdb': 0, 'with_template': 0, 'without_template': 0})
    for entry in report['results']:
        entry['cmdb_name'] = None
        entry['cmdb_templates'] = []
        candidates = [entry['hostname']] + list(entry.get('matched_names') or [])
        for candidate in candidates:
            if candidate not in cmdb_hosts:
                continue
            entry['cmdb_name'] = candidate
            entry['cmdb_templates'] = cmdb_hosts[candidate]
            summary['in_cmdb'] += 1
            if entry['cmdb_templates']:
                summary['with_template'] += 1
            else:
                summary['without_template'] += 1
            break
    return report


def visible_cmdb_hosts(names, template_scope=None):
    """
    Queryset of the syncer hosts named ``names`` a template-restricted
    operator may work with: the hosts carrying one of their templates plus
    the hosts no template has claimed yet — those are the ones the Data
    Quality page lets them take over. Hosts carrying somebody else's
    template stay invisible. ``template_scope`` None = every host.
    """
    # pylint: disable=import-outside-toplevel
    from mongoengine import Q
    from application.models.host import Host
    from application.models.host_templates import template_ids_for_names

    query = Host.objects(hostname__in=list(names), object_type__ne='template',
                         deleted_at__exists=False)
    if template_scope is None:
        return query
    own = list(template_ids_for_names(template_scope))
    # `cmdb_templates.0` misses for every empty shape — field absent, null
    # and empty list — the same test the host list's template filter uses.
    return query.filter(
        Q(cmdb_templates__in=own)
        | Q(__raw__={'cmdb_templates.0': {'$exists': False}}))


def _fetch_cmdb_hosts(names, template_scope=None):
    """
    Map every given name that exists as a syncer host to its CMDB template
    names. Archived templates are left out — they no longer contribute to an
    export — and the template names are resolved from one lookup table instead
    of dereferencing each host's references one by one.

    ``template_scope`` is the caller's CMDB-template allowlist (None for
    unrestricted); everything it hides counts as "not in the CMDB" for the
    report (see :func:`visible_cmdb_hosts`).
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    template_names = {
        template.id: template.hostname
        for template in Host.objects(object_type='template',
                                     deleted_at__exists=False).only('hostname')
    }
    result = {}
    hosts = visible_cmdb_hosts(names, template_scope) \
        .only('hostname', 'cmdb_templates').no_dereference()
    for host in hosts:
        assigned = []
        for reference in host.cmdb_templates or []:
            name = template_names.get(getattr(reference, 'id', reference))
            if name:
                assigned.append(name)
        result[host.hostname] = assigned
    return result


def run_data_quality_check(account_name, hostnames, template_scope=None):
    """
    Run the full data quality check for ``hostnames`` against ``account_name``.

    Instantiates the Checkmk client, fetches the monitoring data in two bulk
    calls, joins it against the uploaded hostnames and adds what the syncer's
    own CMDB knows about them. The Checkmk import is local so this module stays
    importable without the request stack.

    ``template_scope`` limits the CMDB side of the report to hosts carrying
    one of those templates (see :func:`_fetch_cmdb_hosts`).
    """
    # pylint: disable=import-outside-toplevel
    from .cmk2 import CMK2
    cmk = CMK2(account_name)
    monitored_hosts = _fetch_monitored_hosts(cmk)
    checkmk_services = _fetch_checkmk_services(cmk)
    report = build_report(hostnames, monitored_hosts, checkmk_services)
    return attach_cmdb_info(
        report, _fetch_cmdb_hosts(cmdb_candidates(report), template_scope))


def filter_uppercase_hostnames(names):
    """
    Pure: from an iterable of hostnames return the ones that carry uppercase
    letters, each as ``{'name': <original>, 'suggested': <lowercased>}``,
    sorted case-insensitively by name. Checkmk treats hostnames
    case-sensitively, so a mixed-case name is a common data-quality problem.
    """
    hosts = [{'name': name, 'suggested': name.lower()}
             for name in names if name != name.lower()]
    hosts.sort(key=lambda host: host['name'].lower())
    return hosts


def filter_non_fqdn_hostnames(names):
    """
    Pure: from an iterable of hostnames return the ones that are not a
    fully-qualified domain name — i.e. carry no dot — each as ``{'name': ...}``,
    sorted case-insensitively by name.
    """
    hosts = [{'name': name} for name in names if '.' not in name]
    hosts.sort(key=lambda host: host['name'].lower())
    return hosts


def find_uppercase_hosts(account_name):
    """
    Fetch every monitored host of ``account_name`` and return those whose name
    contains uppercase letters. Returns a dict with a ``hosts`` list (see
    :func:`filter_uppercase_hostnames`) and a ``total`` count of hosts scanned.
    """
    return _scan_account(account_name, filter_uppercase_hostnames)


def find_non_fqdn_hosts(account_name):
    """
    Fetch every monitored host of ``account_name`` and return those that are not
    a fully-qualified domain name (no dot). Returns a dict with a ``hosts`` list
    (see :func:`filter_non_fqdn_hostnames`) and a ``total`` count scanned.
    """
    return _scan_account(account_name, filter_non_fqdn_hostnames)


def _scan_account(account_name, name_filter):
    """Fetch the account's monitored hosts and apply ``name_filter`` to them."""
    # pylint: disable=import-outside-toplevel
    from .cmk2 import CMK2
    cmk = CMK2(account_name)
    monitored_hosts = _fetch_monitored_hosts(cmk)
    return {
        'hosts': name_filter(monitored_hosts.keys()),
        'total': len(monitored_hosts),
    }


def cmdb_template_names(template_scope=None):
    """
    Sorted names of the CMDB templates that can be applied to new hosts,
    limited to ``template_scope`` when the operator may only use some of
    them (None = every template).
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host_templates import assignable_templates
    return [h.hostname for h in
            assignable_templates(template_scope)
                .only('hostname').order_by('hostname')]


def apply_domain(hostnames, domain):
    """
    Pure: append ``domain`` to every hostname that carries no domain part.
    Names that already contain a dot keep the domain they came with, so a
    mixed list of short names and FQDNs can be created in one go. An empty
    domain leaves the list unchanged.
    """
    suffix = (domain or '').strip().strip('.')
    if not suffix:
        return list(hostnames)
    return [name if '.' in name else f'{name}.{suffix}' for name in hostnames]


def create_internal_cmdb_hosts(hostnames, template_name=None, domain=None,
                               template_scope=None):
    """
    Create the given hostnames as internal CMDB-managed hosts (source ``cmdb``,
    not CMDB objects), optionally assigning a CMDB template so the new hosts
    inherit its labels/attributes at export time. ``domain`` is appended to
    every name that has no domain part (see :func:`apply_domain`).

    Mirrors the internal-CMDB stamping the Host admin view does on save. Hosts
    that already exist are left untouched and reported under ``skipped``.
    Returns a summary dict with the created and skipped hostnames.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    from application.models.account import (
        CMDB_SOURCE_ACCOUNT_ID, CMDB_SOURCE_ACCOUNT_NAME)

    hostnames = apply_domain(hostnames, domain)
    template = None
    if template_name:
        template = _require_template(template_name, template_scope)

    created = []
    skipped = []
    for hostname in hostnames:
        host = Host.get_host(hostname)
        if not host:
            continue
        if host.id:  # already exists — never overwrite a foreign object
            skipped.append(host.hostname)
            continue
        now = datetime.now()
        host.last_import_sync = now
        host.last_import_seen = now
        # CMDB-managed *host*, not a CMDB object: keep is_object False so the
        # new entries show up in the normal host list (and get exported to
        # Checkmk) instead of landing in the Objects view.
        host.is_object = False
        host.object_type = 'host'
        host.source_account_id = CMDB_SOURCE_ACCOUNT_ID
        host.source_account_name = CMDB_SOURCE_ACCOUNT_NAME
        host.no_autodelete = True
        if template is not None:
            host.cmdb_templates = [template]
        host.set_inventory_attributes(CMDB_SOURCE_ACCOUNT_NAME)
        host.save()
        created.append(host.hostname)
    return {'created': created, 'skipped': skipped, 'template': template_name,
            'domain': domain}


def _require_template(template_name, template_scope=None):
    """
    Look up a CMDB template by name, raising ValueError when it is gone —
    or when ``template_scope`` says the operator may not use it. Both cases
    report the same message: a restricted operator learns nothing about the
    templates other teams work with.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host_templates import get_template
    template = None
    if template_scope is None or template_name in template_scope:
        template = get_template(template_name)
    if template is None:
        raise ValueError(f"CMDB template '{template_name}' not found")
    return template


def assign_cmdb_templates(hostnames, template_name, template_scope=None):
    """
    Give the CMDB template ``template_name`` to hosts that already exist in the
    syncer, keeping the templates they carry already. Raises ValueError when
    the template does not exist or is outside ``template_scope``. Hosts the
    operator may not work with (see :func:`visible_cmdb_hosts`) are reported
    as ``missing`` instead of being touched. Returns the per-outcome hostname
    lists of
    :func:`application.models.host_templates.assign_template_by_hostname`.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host_templates import assign_template_by_hostname
    template = _require_template(template_name, template_scope)
    if template_scope is None:
        return assign_template_by_hostname(template, hostnames)
    allowed = {host.hostname for host in
               visible_cmdb_hosts(hostnames, template_scope).only('hostname')}
    result = assign_template_by_hostname(
        template, [name for name in hostnames if name in allowed])
    result['missing'] += [name for name in hostnames if name not in allowed]
    return result
