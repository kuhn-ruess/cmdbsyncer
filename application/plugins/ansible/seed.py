"""
One-click seed of the Checkmk agent-management rules for an Ansible
project.

`cmk_agent_mngmt.yml` (role `cmk_host_agent`) expects a fixed set of
variables to decide what to do with each host. Filling those in by hand
is tedious and — more importantly — the *actions* (install agent,
register TLS / bakery, discover) must only fire when a condition is met,
not on every host. So instead of one flat rule the seed creates a small
rule set that mirrors that logic:

  1. A base rule (matches every host, 'anyway') that carries the static
     config — credentials, servers, ports, temp dirs — and defaults every
     action flag to `false`.
  2. One conditional rule per action. Each matches on a Checkmk inventory
     attribute and flips a single flag to `true`, overriding the base
     rule's default for the hosts it matches.

Rules are ordered by `sort_field`, and later matching rules override
earlier ones for the same variable — so the base rule (sort 0) supplies
the defaults and the action rules (sort 10+) turn things on where their
condition matches. Everything is created disabled: adapt the server /
credential values and the conditions, then enable.
"""

# --- Base rule: static config + every action defaulted off -------------
# (variable, value) — mirrors ansible/roles/cmk_host_agent/defaults/main.yml
# plus the credential and server variables the tasks read. Booleans are
# stored as the strings "true"/"false"; the inventory converts them to
# real booleans on export.
STATIC_VARIABLES = [
    # Credentials — the secret is read from an Account via the macro.
    ('cmk_user', 'automation'),
    ('cmk_secret', '{{ACCOUNT:CHECKMK:password}}'),
    # Servers / sites — replace with your monitoring addresses.
    ('cmk_main_server', 'monitoring.example.com'),
    ('cmk_main_site', 'cmk'),
    ('cmk_server', 'monitoring.example.com'),
    ('cmk_site', 'cmk'),
    # Paths / ports.
    ('cmk_create_folder', '/inbox'),
    ('cmk_linux_tmp', '/tmp'),
    ('cmk_windows_tmp', 'c:\\temp'),
    ('cmk_agent_receiver_port', '8000'),
    ('cmk_server_port', '443'),
    ('cmk_agent_port', '6556'),
    # Firewall (RedHat).
    ('cmk_agent_configure_firewall_zone', 'public'),
    ('cmk_server_ip', 'false'),
    ('cmk_main_server_ip', 'false'),
    ('configure_firewall', 'false'),
    # TLS.
    ('validate_certs', 'true'),
    # Action flags — all OFF here; the conditional rules below turn the
    # relevant one on for the hosts that need it.
    ('cmk_create_host', 'false'),
    ('cmk_install_agent', 'false'),
    ('cmk_register_tls', 'false'),
    ('cmk_register_bakery', 'false'),
    ('cmk_register_central_bakery', 'false'),
    ('cmk_discover', 'false'),
    ('cmk_delete_manual_files', 'false'),
]

# --- Conditional action rules ------------------------------------------
# Each entry is a dict: suffix, sort_field, condition_typ, documentation,
# a list of conditions (attribute_key, match, value) and a list of
# outcomes (name, value). A condition's attribute key is matched exactly
# and its value tested with `match` ('in' = contains).
#
# The conditions mirror the maintainer's reference rule set: when a host's
# agent is missing or unreachable, Checkmk's own "Check_MK" service reports
# `[agent] Empty output` / `[agent] Communication failed`. That is the
# signal to (re)install the agent and register TLS + bakery and run a
# discovery — all together, since a broken agent needs the full cycle. The
# service output is inventorized under `cmk_svc__check_mk_output` (run
# `checkmk inventorize_hosts` with service collection enabled). Verify the
# outcome for a host with `./cmdbsyncer ansible debug_host HOST`.
ACTION_RULES = [
    {
        'suffix': 'Install Agent',
        'sort_field': 10,
        'condition_typ': 'any',
        'documentation': (
            "(Re)install the Checkmk agent where it is missing or unreachable "
            "— Checkmk's 'Check_MK' service then reports '[agent] Empty "
            "output' or '[agent] Communication failed'. Once the agent is "
            "back, the TLS / bakery / discovery rules below take over on the "
            "next inventorize."
        ),
        'conditions': [
            ('cmk_svc__check_mk_output', 'in', '[agent] Empty output'),
            ('cmk_svc__check_mk_output', 'in', '[agent] Communication failed'),
        ],
        'outcomes': [('cmk_install_agent', 'true')],
    },
    {
        'suffix': 'Register TLS',
        'sort_field': 20,
        'condition_typ': 'all',
        'documentation': (
            "Register agent TLS only where the agent is reachable but not "
            "TLS-registered — Checkmk's 'Check_MK' service reports 'TLS is "
            "not activated on monitored host'. Adjust the wording for your "
            "Checkmk version if needed."
        ),
        'conditions': [
            ('cmk_svc__check_mk_agent_output', 'in', 'TLS is not activated on monitored host'),
        ],
        'outcomes': [('cmk_register_tls', 'true')],
    },
    {
        'suffix': 'Register Bakery',
        'sort_field': 30,
        'condition_typ': 'all',
        'documentation': (
            "Register with the bakery only where the deployment registration "
            "is missing — the agent updater service ('Check_MK Agent') "
            "reports the host is not registered. Verify the exact wording "
            "against your Checkmk version with `debug_host`."
        ),
        'conditions': [
            ('cmk_svc__check_mk_agent_output', 'in', 'not registered'),
        ],
        'outcomes': [('cmk_register_bakery', 'true')],
    },
    {
        'suffix': 'Run Discovery',
        'sort_field': 40,
        'condition_typ': 'all',
        'documentation': (
            "Run a service discovery only where Checkmk's 'Check_MK "
            "Discovery' service reports unmonitored services."
        ),
        'conditions': [
            ('cmk_svc__check_mk_discovery_output', 'in', 'unmonitored'),
        ],
        'outcomes': [('cmk_discover', 'true')],
    },
]

BASE_RULE_SUFFIX = 'Agent Base Config'


def _rule_name(project, suffix):
    """Deterministic rule name so re-seeding is idempotent (existing rules
    are detected by name and left untouched)."""
    return f"{project.name} - {suffix}"


def _tag_condition(attribute_key, value_match, value):
    """Build a FullCondition that matches a specific attribute key exactly
    and tests its value."""
    from application.modules.rule.models import FullCondition  # pylint: disable=import-outside-toplevel
    return FullCondition(
        match_type='tag',
        tag_match='equal',
        tag=attribute_key,
        tag_match_negate=False,
        value_match=value_match,
        value=value,
        value_match_negate=False,
    )


def _build_cmk_agent_specs(project):
    """
    Rule specs for the Checkmk agent-management template: one base rule
    with the static config, then the conditional action rule(s). Each spec
    is a dict ready to splat into its `model` constructor; `model` lets a
    template seed any rule type, not just Custom Variables.
    """
    from application.modules.rule.models import CustomAttribute  # pylint: disable=import-outside-toplevel
    from .models import AnsibleCustomVariablesRule  # pylint: disable=import-outside-toplevel

    def _outcomes(pairs):
        return [
            CustomAttribute(attribute_name=name, attribute_value=value)
            for name, value in pairs
        ]

    specs = [{
        'model': AnsibleCustomVariablesRule,
        'name': _rule_name(project, BASE_RULE_SUFFIX),
        'documentation': (
            "Static Checkmk config and credentials, applied to every host. "
            "Adapt the server and credential values. All actions default to "
            "off here — the conditional rules turn them on where needed."
        ),
        'project': project,
        'condition_typ': 'anyway',
        'conditions': [],
        'outcomes': _outcomes(STATIC_VARIABLES),
        'enabled': False,
        'sort_field': 0,
    }]
    for rule in ACTION_RULES:
        specs.append({
            'model': AnsibleCustomVariablesRule,
            'name': _rule_name(project, rule['suffix']),
            'documentation': rule['documentation'],
            'project': project,
            'condition_typ': rule['condition_typ'],
            'conditions': [
                _tag_condition(key, value_match, value)
                for key, value_match, value in rule['conditions']
            ],
            'outcomes': _outcomes(rule['outcomes']),
            'enabled': False,
            'sort_field': rule['sort_field'],
        })
    return specs


# Registry of seed templates. Each entry describes one "one-click" seed a
# project can apply; the button on the project page renders one action per
# registered template. Adding a future template (e.g. a Netbox or LDAP
# starter set, or Filter/Rewrite rules) is just another
# `register_seed_template(...)` call — the endpoint, button, and idempotent
# create logic are all generic over this registry.
SEED_TEMPLATES = {}


def register_seed_template(key, label, builder):
    """
    Register a seed template.

    key     — stable identifier used in the seed URL.
    label   — button label shown on the project page.
    builder — callable(project) -> list of rule spec dicts, each carrying a
              `model` key plus the constructor kwargs for that model.
    """
    SEED_TEMPLATES[key] = {'label': label, 'builder': builder}


register_seed_template('cmk_agent', 'Checkmk Agent rules', _build_cmk_agent_specs)


def seed_project(project, key):
    """
    Apply the seed template `key` to `project`.

    Idempotent — a rule whose name already exists (in its own model's
    collection) is skipped, so re-running only fills in what is missing.
    Every created rule is disabled: adapt the values / conditions, then
    enable.

    Returns (created_names, skipped_names), or None if `key` is unknown.
    """
    template = SEED_TEMPLATES.get(key)
    if template is None:
        return None
    created, skipped = [], []
    for spec in template['builder'](project):
        model = spec.pop('model')
        if model.objects(name=spec['name']).first():
            skipped.append(spec['name'])
            continue
        model(**spec).save()
        created.append(spec['name'])
    return created, skipped
