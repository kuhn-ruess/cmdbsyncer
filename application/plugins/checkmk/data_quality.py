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
    short_index = {}
    for name in monitored_hosts:
        short_index.setdefault(_short_name(name), []).append(name)

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
        if hostname in monitored_hosts:
            entry['status'] = 'found'
            entry['cmk_name'] = hostname
            summary['found'] += 1
        else:
            matches = short_index.get(_short_name(hostname), [])
            if matches:
                entry['status'] = 'domain_mismatch'
                entry['cmk_name'] = matches[0]
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


def run_data_quality_check(account_name, hostnames):
    """
    Run the full data quality check for ``hostnames`` against ``account_name``.

    Instantiates the Checkmk client, fetches the monitoring data in two bulk
    calls and joins it against the uploaded hostnames. The Checkmk import is
    local so this module stays importable without the request stack.
    """
    # pylint: disable=import-outside-toplevel
    from .cmk2 import CMK2
    cmk = CMK2(account_name)
    monitored_hosts = _fetch_monitored_hosts(cmk)
    checkmk_services = _fetch_checkmk_services(cmk)
    return build_report(hostnames, monitored_hosts, checkmk_services)


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


def cmdb_template_names():
    """Sorted names of the CMDB templates that can be applied to new hosts."""
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    return [h.hostname for h in
            Host.objects(object_type='template', deleted_at__exists=False)
                .only('hostname').order_by('hostname')]


def create_internal_cmdb_hosts(hostnames, template_name=None):
    """
    Create the given hostnames as internal CMDB-managed hosts (source ``cmdb``,
    not CMDB objects), optionally assigning a CMDB template so the new hosts
    inherit its labels/attributes at export time.

    Mirrors the internal-CMDB stamping the Host admin view does on save. Hosts
    that already exist are left untouched and reported under ``skipped``.
    Returns a summary dict with the created and skipped hostnames.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    from application.models.account import (
        CMDB_SOURCE_ACCOUNT_ID, CMDB_SOURCE_ACCOUNT_NAME)

    template = None
    if template_name:
        template = Host.objects(hostname=template_name, object_type='template',
                                deleted_at__exists=False).first()
        if template is None:
            raise ValueError(f"CMDB template '{template_name}' not found")

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
    return {'created': created, 'skipped': skipped, 'template': template_name}
