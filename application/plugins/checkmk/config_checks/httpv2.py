"""
Check HTTP web service (``check_httpv2``): duplicate and mergeable checks.

The old ``check_http`` needed one rule for the web page and a second one for
the certificate. ``check_httpv2`` checks both in one endpoint, but the
migration (``cmk-migrate-http``) turns every old rule into its own new rule,
so a site carries two checks per URL where one is enough.

How endpoints are compared
--------------------------
Every endpoint of every enabled rule of ``active_checks:httpv2`` gets its
effective settings: the rule's standard settings overwritten key by key by
the endpoint's individual settings (the same merge Checkmk does).

Two endpoints check the *same target* when

* their rules sit in the same folder,
* their rules have the same conditions (host names, tags, labels, ...;
  empty conditions count as absent),
* their URLs are equal after normalising (scheme and host lowercased,
  the default port 80/443 and an empty path ``/`` dropped),
* and they connect to the same server (``server`` setting, empty when
  the URL host is used).

Within a group of endpoints on the same target:

* **Duplicate**: endpoints with identical effective settings (the service
  name may differ). One of them is enough.
* **Mergeable**: a certificate-only endpoint next to an endpoint that
  checks the web page. Certificate-only means the certificate is validated
  with expiry levels (``cert: ('validate', ('fixed', ...))``) and none of
  ``server_response``, ``content``, ``response_time`` or a ``document``
  setting other than ignoring the body is set. The certificate levels can
  move into the web page endpoint and the certificate-only endpoint can go.
* **Same URL**: anything else with more than one endpoint, e.g. two web
  page checks with different expected content. Often intended, listed as
  information.

Rules still in the old ``active_checks:http`` ruleset are reported: as not
migrated, or as still running next to their new rule when a new rule
carries the ``Migrated from v1: <id>`` comment of an unfinished
``cmk-migrate-http`` run. Disabled rules are skipped.

Failing checks
--------------
Every HTTP check service (``check_httpv2`` and the old ``check_http``) that
is not OK in the monitoring right now (WARN, CRIT or UNKNOWN) is reported
with host, service, state and plugin output. The rule behind it is named
when the service name of an enabled endpoint matches exactly; service
names built from macros cannot be traced back.
"""
import json
from urllib.parse import urlsplit, urlunsplit

from . import register_check
from .base import (
    Column, ConfigCheck, Finding, Topic, SEVERITY_INFO, fetch_rules,
    condition_key, describe_conditions)

RULESET = 'active_checks:httpv2'
LEGACY_RULESET = 'active_checks:http'

# Settings that make an endpoint look at the web page itself.
CONTENT_KEYS = ('server_response', 'content', 'response_time')
DEFAULT_PORTS = {'http': '80', 'https': '443'}
DAY = 86400
MIGRATED_MARKER = 'Migrated from v1:'
SERVICE_STATES = {1: 'WARN', 2: 'CRIT', 3: 'UNKNOWN'}
# check_command of the HTTP active checks, new and old.
HTTP_COMMAND_REGEX = '^check_mk_active-http(v2)?!'

_SCOPE = (Column('url', 'URL', 'code'), Column('folder', 'Folder', 'code'),
          Column('conditions', 'Conditions'))
_LEGACY_COLUMNS = (Column('name', 'Name'), Column('folder', 'Folder', 'code'),
                   Column('conditions', 'Conditions'),
                   Column('rules', 'Old rule', 'items'))

TOPIC_FAILING = Topic(
    'failing', 'HTTP checks not OK',
    "These HTTP check services (check_httpv2 and the old check_http) are "
    "WARN, CRIT or UNKNOWN in the monitoring right now. The rule behind a "
    "service is named when its service name matches a rule.",
    "Fix the web service, or the rule if it checks something that is not "
    "there any more.",
    (Column('host', 'Host', 'code'), Column('service', 'Service'),
     Column('state', 'State', 'state'), Column('output', 'Output'),
     Column('rules', 'Rule', 'items')))
TOPIC_DUPLICATE = Topic(
    'duplicate', 'Duplicate checks',
    "Two or more endpoints check the same URL for the same hosts with "
    "identical settings. Only the service name may differ.",
    "Keep one of them and remove the others.",
    _SCOPE + (Column('checks', 'Identical checks', 'items'),))
TOPIC_MERGEABLE = Topic(
    'mergeable', 'Website and certificate checked separately',
    "One endpoint only checks the certificate, another one checks the web "
    "page of the same URL for the same hosts. Typical after the migration "
    "from check_http, which needed two rules for this. check_httpv2 does "
    "both in one endpoint.",
    "Set 'Certificate validity' of the website check to 'Check "
    "certificate' with the levels of the certificate check, then remove "
    "the certificate check.",
    _SCOPE + (Column('website', 'Website check', 'items'),
              Column('certificate', 'Certificate check', 'items'),
              Column('recommendation', 'What to do')))
TOPIC_SAME_URL = Topic(
    'same_url', 'Several checks on the same URL',
    "More than one endpoint with different settings checks the same URL "
    "for the same hosts, e.g. with different expected content. Often "
    "intended.",
    "Check whether all of them are needed.",
    _SCOPE + (Column('checks', 'Checks', 'items'),),
    severity=SEVERITY_INFO)
TOPIC_NOT_FINALIZED = Topic(
    'not_finalized', 'Migration not finalized',
    "cmk-migrate-http created a new rule from these old check_http rules, "
    "but the old rules are still active: both run.",
    "Finalize the migration (cmk-migrate-http finalize) or disable the old "
    "rules.",
    _LEGACY_COLUMNS)
TOPIC_NOT_MIGRATED = Topic(
    'not_migrated', 'Old check_http rules not migrated',
    "These rules still use the old check_http and have no check_httpv2 "
    "counterpart, e.g. because the migration skipped them.",
    "Migrate them to 'Check HTTP web service' (cmk-migrate-http), or by "
    "hand if the migration skips them.",
    _LEGACY_COLUMNS)


def normalize_url(url):
    """Comparable form of an endpoint URL (see the module docstring)."""
    url = (url or '').strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    host, _, port = netloc.rpartition(':')
    if host and port == DEFAULT_PORTS.get(scheme):
        netloc = host
    return urlunsplit((scheme, netloc, parts.path or '/', parts.query, ''))


def effective_settings(value, endpoint):
    """Standard settings overwritten by the endpoint's individual ones."""
    return {**(value.get('standard_settings') or {}),
            **(endpoint.get('individual_settings') or {})}


def cert_levels(settings):
    """``(warn_days, crit_days)`` when the certificate expiry is checked."""
    cert = settings.get('cert')
    if not (isinstance(cert, (tuple, list)) and len(cert) == 2
            and cert[0] == 'validate'):
        return None
    levels = cert[1]
    if isinstance(levels, (tuple, list)) and len(levels) == 2 \
            and levels[0] == 'fixed':
        warn, crit = levels[1]
        return (round(warn / DAY), round(crit / DAY))
    return None


def checks_content(settings):
    """Whether the endpoint looks at the web page, not only the certificate."""
    if any(settings.get(key) for key in CONTENT_KEYS):
        return True
    document = settings.get('document')
    return bool(document) and document != {'document_body': 'ignore'}


def endpoint_role(settings):
    """``certificate``, ``website`` or ``website + certificate``."""
    has_cert = cert_levels(settings) is not None
    if has_cert and not checks_content(settings):
        return 'certificate'
    if has_cert:
        return 'website + certificate'
    return 'website'


def service_name(endpoint):
    """The service name the endpoint creates (macros left as they are)."""
    naming = endpoint.get('service_name') or {}
    name = naming.get('name', '')
    if naming.get('prefix', 'auto') == 'auto':
        prefix = 'HTTPS' if (endpoint.get('url') or '').startswith('https://') \
            else 'HTTP'
        return f"{prefix} {name}"
    return name


def collect_endpoints(rules):
    """
    Flatten the enabled rules into one entry per endpoint. Returns
    ``(endpoints, skipped)``; ``skipped`` counts rules whose value could
    not be read.
    """
    endpoints = []
    skipped = 0
    for rule in rules:
        if rule['disabled']:
            continue
        value = rule['value']
        if not isinstance(value, dict) \
                or not isinstance(value.get('endpoints'), (list, tuple)):
            skipped += 1
            continue
        for endpoint in value['endpoints']:
            settings = effective_settings(value, endpoint)
            endpoints.append({
                'rule': rule,
                'url': endpoint.get('url', ''),
                'service': service_name(endpoint),
                'settings': settings,
                'role': endpoint_role(settings),
                'target': (rule['folder'], condition_key(rule['conditions']),
                           normalize_url(endpoint.get('url')),
                           str(settings.get('server') or '')),
            })
    return endpoints, skipped


def _item(endpoint, detail=''):
    rule = endpoint['rule']
    return {
        'rule_id': rule['id'],
        'rule': rule['description'],
        'folder': rule['folder'],
        'service': endpoint['service'],
        'detail': detail or endpoint['role'],
    }


def _settings_key(settings):
    return json.dumps(settings, sort_keys=True, default=str)


def _differing_keys(left, right, ignore):
    """Names (never values: they may hold credentials) of differing settings."""
    keys = (set(left) | set(right)) - set(ignore)
    return sorted(key for key in keys if left.get(key) != right.get(key))


def _scope(group):
    """The URL, folder and conditions cells a group of endpoints shares."""
    rule = group[0]['rule']
    return {'url': group[0]['url'], 'folder': rule['folder'],
            'conditions': describe_conditions(rule['conditions'])}


def _duplicates(group):
    """Split off identical endpoints. Returns ``(findings, unique)``."""
    by_settings = {}
    for endpoint in group:
        by_settings.setdefault(_settings_key(endpoint['settings']), []) \
            .append(endpoint)
    findings = []
    unique = []
    for same in by_settings.values():
        unique.append(same[0])
        if len(same) > 1:
            findings.append(Finding(TOPIC_DUPLICATE.key, {
                **_scope(same), 'checks': [_item(e) for e in same]}))
    return findings, unique


def _mergeable(group):
    """The finding for certificate-only endpoints next to a web page check."""
    certs = [e for e in group if e['role'] == 'certificate']
    pages = [e for e in group if e['role'] != 'certificate']
    if not certs or not pages:
        return None
    page = pages[0]
    cert_items = []
    for cert in certs:
        warn, crit = cert_levels(cert['settings'])
        detail = f"certificate only, warn {warn} / crit {crit} days"
        others = _differing_keys(page['settings'], cert['settings'],
                                 ignore=('cert', 'document') + CONTENT_KEYS)
        if others:
            detail += f"; other settings differ: {', '.join(others)}"
        cert_items.append(_item(cert, detail))
    if page['role'] == 'website':
        recommendation = (
            f"Set 'Certificate validity' of '{page['service']}' to "
            "'Check certificate' with the levels of the certificate check, "
            "then remove the certificate check.")
    else:
        recommendation = (f"'{page['service']}' already checks the "
                          "certificate: remove the certificate check.")
    return Finding(TOPIC_MERGEABLE.key, {
        **_scope(group), 'website': [_item(e) for e in pages],
        'certificate': cert_items, 'recommendation': recommendation})


def analyze_endpoints(endpoints):
    """Pure: the findings for a list of endpoints from :func:`collect_endpoints`."""
    groups = {}
    for endpoint in endpoints:
        groups.setdefault(endpoint['target'], []).append(endpoint)
    findings = []
    for group in groups.values():
        if len(group) < 2:
            continue
        duplicates, unique = _duplicates(group)
        findings += duplicates
        if len(unique) < 2:
            continue
        mergeable = _mergeable(unique)
        if mergeable:
            findings.append(mergeable)
            continue
        findings.append(Finding(TOPIC_SAME_URL.key, {
            **_scope(unique), 'checks': [_item(e) for e in unique]}))
    return findings


def migrated_ids(rules):
    """
    Ids of the old rules ``cmk-migrate-http`` made the given new rules from.
    Until the migration is finalized it notes them in the rule comment.
    """
    ids = set()
    for rule in rules:
        for line in rule.get('comment', '').splitlines():
            if line.startswith(MIGRATED_MARKER):
                ids.add(line[len(MIGRATED_MARKER):].strip())
    return ids


def legacy_findings(rules, migrated=frozenset()):
    """
    Pure: one finding per enabled rule still in the old http ruleset, under
    "not migrated", or under "not finalized" when its id is in ``migrated``
    (see :func:`migrated_ids`): those run twice until the migration is
    finalized.
    """
    findings = []
    for rule in rules:
        if rule['disabled']:
            continue
        value = rule['value'] if isinstance(rule['value'], dict) else {}
        name = value.get('name', '')
        topic = TOPIC_NOT_FINALIZED if rule['id'] in migrated \
            else TOPIC_NOT_MIGRATED
        findings.append(Finding(topic.key, {
            'name': name or rule['id'], 'folder': rule['folder'],
            'conditions': describe_conditions(rule['conditions']),
            'rules': [{'rule_id': rule['id'], 'rule': rule['description'],
                       'detail': 'active_checks:http'}]}))
    return findings


def fetch_failing_services(cmk):
    """Every HTTP check service that is not OK, read from the monitoring."""
    query = {"op": "and", "expr": [
        {"op": "~", "left": "check_command", "right": HTTP_COMMAND_REGEX},
        {"op": "!=", "left": "state", "right": "0"},
    ]}
    params = {
        "query": json.dumps(query),
        "columns": ['host_name', 'description', 'state', 'plugin_output',
                    'check_command'],
    }
    data, _headers = cmk.request("domain-types/service/collections/all",
                                 method="GET", params=params)
    services = []
    for row in data.get('value', []) or []:
        ext = row.get('extensions', {}) or {}
        services.append({
            'host_name': ext.get('host_name', ''),
            'description': ext.get('description', ''),
            'state': ext.get('state'),
            'output': ext.get('plugin_output', '') or '',
            'legacy': not str(ext.get('check_command', ''))
                      .startswith('check_mk_active-httpv2'),
        })
    return services


def _legacy_items_by_service(legacy_rules):
    """
    Old check_http rules by the service names they can create: ``HTTP`` or
    ``HTTPS`` plus the rule's name, the bare name when it starts with ``^``.
    """
    by_service = {}
    for rule in legacy_rules:
        value = rule['value'] if isinstance(rule['value'], dict) else {}
        name = value.get('name', '')
        if rule['disabled'] or not name:
            continue
        names = [name[1:]] if name.startswith('^') \
            else [f'HTTP {name}', f'HTTPS {name}']
        item = {'rule_id': rule['id'], 'rule': rule['description'],
                'folder': rule['folder'], 'detail': 'old check_http rule'}
        for service in names:
            by_service.setdefault(service, []).append(item)
    return by_service


def failing_findings(services, endpoints, legacy_rules=()):
    """
    Pure: one finding per HTTP check service that is not OK, worst state
    first. ``endpoints`` (from :func:`collect_endpoints`) and the old
    ``legacy_rules`` name the rule behind a service when their service
    name matches.
    """
    by_service = {}
    for endpoint in endpoints:
        by_service.setdefault(endpoint['service'], []).append(
            {**_item(endpoint, endpoint['url']), 'service': ''})
    legacy_by_service = _legacy_items_by_service(legacy_rules)
    findings = []
    for service in sorted(services, key=lambda s: (-(s['state'] or 0),
                                                   s['host_name'],
                                                   s['description'])):
        if not service['state']:
            continue
        source = legacy_by_service if service['legacy'] else by_service
        findings.append(Finding(TOPIC_FAILING.key, {
            'host': service['host_name'], 'service': service['description'],
            'state': SERVICE_STATES.get(service['state'], str(service['state'])),
            'output': service['output'],
            'rules': source.get(service['description']) or [{
                'detail': 'not traced (service name differs or uses macros)'}],
        }))
    return findings


@register_check
class HttpV2Check(ConfigCheck):
    """HTTP checks that fail, check twice or are not migrated."""
    name = 'httpv2'
    title = 'HTTP web service checks (check_httpv2)'
    description = (
        "Lists the HTTP check services that are WARN, CRIT or UNKNOWN, "
        "endpoints of the 'Check HTTP web service' rules that check the same "
        "URL twice, website and certificate checks that can be merged into "
        "one, and rules still on the old check_http.")
    topics = (TOPIC_FAILING, TOPIC_DUPLICATE, TOPIC_MERGEABLE,
              TOPIC_SAME_URL, TOPIC_NOT_FINALIZED, TOPIC_NOT_MIGRATED)

    def analyze(self, cmk):
        rules = fetch_rules(cmk, RULESET)
        legacy = fetch_rules(cmk, LEGACY_RULESET)
        services = fetch_failing_services(cmk)
        endpoints, skipped = collect_endpoints(rules)
        findings = failing_findings(services, endpoints, legacy) \
            + analyze_endpoints(endpoints) \
            + legacy_findings(legacy, migrated_ids(rules))
        stats = [
            ('check_httpv2 rules', len(rules)),
            ('Disabled rules skipped', sum(1 for r in rules if r['disabled'])),
            ('Endpoints compared', len(endpoints)),
            ('Unreadable rules skipped', skipped),
            ('Old check_http rules', sum(1 for r in legacy if not r['disabled'])),
            ('HTTP checks not OK', len(services)),
        ]
        return findings, stats
