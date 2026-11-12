"""
Unhandled problems: what the monitoring reports right now and nobody took
care of yet, grouped by kind so it can be worked off topic by topic.

A problem counts as *unhandled* like in the Checkmk views: it is not
acknowledged and neither it nor its host is in a scheduled downtime.
Services on a host that is DOWN or UNREACHABLE are left out, the host is
the problem there.

The problems are split into

* hosts DOWN or UNREACHABLE,
* the ``Check_MK`` service: the agent or another data source fails, so the
  host's other services are not updated,
* the ``Check_MK Discovery`` service: services or host labels changed and
  wait for a service discovery,
* every other service, grouped by check type (the check plugin, or the
  active check), the type with the worst state and the most services first.
"""
import json
from collections import Counter

from . import register_check
from .base import Column, ConfigCheck, Finding, Topic

HOST_STATES = {1: 'DOWN', 2: 'UNREACHABLE'}
SERVICE_STATES = {1: 'WARN', 2: 'CRIT', 3: 'UNKNOWN'}
# Worst first: CRIT, UNKNOWN, WARN (the order Checkmk sorts by).
STATE_RANK = {2: 0, 3: 1, 1: 2}
AGENT_SERVICE = 'Check_MK'
DISCOVERY_SERVICE = 'Check_MK Discovery'

_HOST_COLUMNS = (Column('host', 'Host', 'code'),
                 Column('state', 'State', 'state'),
                 Column('output', 'Output'))

TOPIC_HOSTS = Topic(
    'hosts', 'Hosts DOWN or UNREACHABLE',
    "These hosts are DOWN or UNREACHABLE, not acknowledged and not in a "
    "downtime. Their services are not listed in the other topics.",
    "Bring the host back, set a downtime for planned work, or remove the "
    "host from the monitoring if it is gone.",
    _HOST_COLUMNS)
TOPIC_AGENT = Topic(
    'agent', 'Agent or data source fails',
    "The Check_MK service of these hosts is not OK: the agent, SNMP or a "
    "special agent did not deliver data, so the other services of the host "
    "are not updated.",
    "Fix the connection to the agent or the data source (firewall, agent "
    "installed and registered, SNMP credentials, special agent settings).",
    _HOST_COLUMNS)
TOPIC_DISCOVERY = Topic(
    'discovery', 'Service discovery pending',
    "The Check_MK Discovery service of these hosts reports unmonitored or "
    "vanished services or changed host labels.",
    "Run a service discovery on the hosts and accept the changes, or "
    "disable the services that should not be monitored.",
    _HOST_COLUMNS, host_action='discovery')
TOPIC_BY_TYPE = Topic(
    'by_type', 'Service problems by check type',
    "Every other service that is WARN, CRIT or UNKNOWN, one row per check "
    "type. The same problem on many hosts usually has one cause.",
    "Work through the check types from the top: fix the cause, adjust the "
    "levels of the check if they do not fit, or acknowledge the problem.",
    (Column('check_type', 'Check type', 'code'),
     Column('state', 'Worst', 'state'),
     Column('summary', 'Count'),
     Column('services', 'Services', 'items')))


def _rows(data):
    return [row.get('extensions', {}) or {} for row in data.get('value', []) or []]


def fetch_host_problems(cmk):
    """Every host that is not UP, with its handling state (one API call)."""
    params = {
        "query": json.dumps({"op": "!=", "left": "state", "right": "0"}),
        "columns": ['name', 'state', 'plugin_output', 'acknowledged',
                    'scheduled_downtime_depth'],
    }
    data, _headers = cmk.request("domain-types/host/collections/all",
                                 method="GET", params=params)
    return _rows(data)


def fetch_service_problems(cmk):
    """Every service that is not OK, with its handling state (one API call)."""
    params = {
        "query": json.dumps({"op": "!=", "left": "state", "right": "0"}),
        "columns": ['host_name', 'description', 'state', 'plugin_output',
                    'check_command', 'acknowledged', 'scheduled_downtime_depth',
                    'host_state', 'host_scheduled_downtime_depth'],
    }
    data, _headers = cmk.request("domain-types/service/collections/all",
                                 method="GET", params=params)
    return _rows(data)


def check_type(command):
    """
    The readable check type of a ``check_command``: the check plugin
    (``check_mk-df`` is ``df``), ``http (active check)`` for
    ``check_mk_active-http!...``, otherwise the command without arguments.
    """
    command = str(command or '').split('!', 1)[0]
    if command.startswith('check_mk_active-'):
        return f"{command[len('check_mk_active-'):]} (active check)"
    if command.startswith('check_mk-'):
        return command[len('check_mk-'):]
    return command or 'unknown'


def _handled(row, host_prefix=''):
    """Acknowledged, or the object or its host in a downtime."""
    return bool(row.get('acknowledged')) \
        or bool(row.get('scheduled_downtime_depth')) \
        or bool(row.get(f'{host_prefix}scheduled_downtime_depth'))


def _host_finding(topic, name, state, states, output):
    return Finding(topic.key, {'host': name,
                               'state': states.get(state, str(state)),
                               'output': output or ''})


def host_findings(hosts):
    """Pure: ``(findings, handled)`` for the rows of :func:`fetch_host_problems`."""
    findings = []
    handled = 0
    for row in sorted(hosts, key=lambda r: (-(r.get('state') or 0),
                                            r.get('name', ''))):
        if not row.get('state'):
            continue
        if _handled(row):
            handled += 1
            continue
        findings.append(_host_finding(TOPIC_HOSTS, row.get('name', ''),
                                      row.get('state'), HOST_STATES,
                                      row.get('plugin_output')))
    return findings, handled


def _summary(services):
    states = Counter(s['state'] for s in services)
    parts = ', '.join(f"{states[state]} {SERVICE_STATES[state]}"
                      for state in sorted(states, key=STATE_RANK.get))
    hosts = len({s['host_name'] for s in services})
    word = 'host' if hosts == 1 else 'hosts'
    return f"{len(services)} ({parts}) on {hosts} {word}"


def _type_finding(name, services):
    services = sorted(services, key=lambda s: (STATE_RANK[s['state']],
                                               s['host_name'], s['description']))
    return Finding(TOPIC_BY_TYPE.key, {
        'check_type': name,
        'state': SERVICE_STATES[services[0]['state']],
        'summary': _summary(services),
        'services': [{'service': s['host_name'], 'rule': s['description'],
                      'detail': f"{SERVICE_STATES[s['state']]}: "
                                f"{s['plugin_output'] or ''}"}
                     for s in services],
    })


def service_findings(services):
    """
    Pure: ``(findings, handled, on_host_problem)`` for the rows of
    :func:`fetch_service_problems`. ``handled`` counts acknowledged services
    and services in a downtime, ``on_host_problem`` those left out because
    their host is not UP.
    """
    agent, discovery, by_type = [], [], {}
    handled = on_host_problem = 0
    for row in services:
        if row.get('state') not in SERVICE_STATES:
            continue
        if _handled(row, 'host_'):
            handled += 1
            continue
        if row.get('host_state'):
            on_host_problem += 1
            continue
        service = {'host_name': row.get('host_name', ''),
                   'description': row.get('description', ''),
                   'state': row['state'],
                   'plugin_output': row.get('plugin_output') or ''}
        if service['description'] == AGENT_SERVICE:
            agent.append(service)
        elif service['description'] == DISCOVERY_SERVICE:
            discovery.append(service)
        else:
            by_type.setdefault(check_type(row.get('check_command')), []) \
                .append(service)

    def by_host(rows, topic):
        rows = sorted(rows, key=lambda s: (STATE_RANK[s['state']], s['host_name']))
        return [_host_finding(topic, s['host_name'], s['state'], SERVICE_STATES,
                              s['plugin_output']) for s in rows]

    order = sorted(by_type, key=lambda name: (
        min(STATE_RANK[s['state']] for s in by_type[name]),
        -len(by_type[name]), name))
    types = [_type_finding(name, by_type[name]) for name in order]
    findings = by_host(agent, TOPIC_AGENT) + by_host(discovery, TOPIC_DISCOVERY) \
        + types
    return findings, handled, on_host_problem


@register_check
class UnhandledProblemsCheck(ConfigCheck):
    """Unhandled host and service problems, grouped by kind."""
    name = 'unhandled'
    title = 'Unhandled problems'
    description = (
        "Lists the host and service problems in the monitoring that are not "
        "acknowledged and not in a downtime, grouped to work them off: hosts "
        "DOWN, failing agents, pending service discoveries and the other "
        "service problems by check type.")
    topics = (TOPIC_HOSTS, TOPIC_AGENT, TOPIC_DISCOVERY, TOPIC_BY_TYPE)

    def analyze(self, cmk):
        hosts = fetch_host_problems(cmk)
        services = fetch_service_problems(cmk)
        host_found, hosts_handled = host_findings(hosts)
        service_found, services_handled, on_host_problem = \
            service_findings(services)
        stats = [
            ('Hosts not UP', len(hosts)),
            ('Hosts acknowledged or in downtime', hosts_handled),
            ('Services not OK', len(services)),
            ('Services acknowledged or in downtime', services_handled),
            ('Services on hosts not UP', on_host_problem),
        ]
        return host_found + service_found, stats
