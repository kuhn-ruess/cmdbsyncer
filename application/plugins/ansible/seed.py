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
# Each entry: (suffix, sort_field, documentation, condition, outcomes).
# `condition` is (attribute_key, match, value): the attribute key is
# matched exactly, its value is tested with `match` ('in' = contains).
# The keys are the ones Checkmk inventorize writes (source `cmk_svc`, so
# each service output is `cmk_svc__<service>_output`). The value strings
# are examples from typical Checkmk output — verify them against
# `./cmdbsyncer ansible debug_host HOST` and adapt to your environment.
ACTION_RULES = [
    (
        'Install Agent',
        10,
        "Install / update the Checkmk agent where the agent updater "
        "reports a version mismatch. Adapt the condition to your setup.",
        ('cmk_svc__check_mk_agent_output', 'in', 'is not the same as'),
        [('cmk_install_agent', 'true')],
    ),
    (
        'Register TLS',
        20,
        "Register agent TLS where the Check_MK service reports that TLS is "
        "not activated on the monitored host.",
        ('cmk_svc__check_mk_output', 'in', 'TLS is not activated'),
        [('cmk_register_tls', 'true')],
    ),
    (
        'Register Bakery',
        30,
        "Register with the bakery where the agent updater reports the host "
        "is not registered for deployment.",
        ('cmk_svc__check_mk_agent_output', 'in', 'not registered'),
        [('cmk_register_bakery', 'true')],
    ),
    (
        'Discover Services',
        40,
        "Run a service discovery where Check_MK Discovery reports "
        "unmonitored services.",
        ('cmk_svc__check_mk_discovery_output', 'in', 'unmonitored'),
        [('cmk_discover', 'true')],
    ),
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


def _build_rule_specs(project):
    """
    Return the list of rule specs the seed creates, each a dict ready to
    splat into AnsibleCustomVariablesRule(): the base rule first, then one
    conditional rule per action.
    """
    from application.modules.rule.models import CustomAttribute  # pylint: disable=import-outside-toplevel

    def _outcomes(pairs):
        return [
            CustomAttribute(attribute_name=name, attribute_value=value)
            for name, value in pairs
        ]

    specs = [{
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
    for suffix, sort_field, doc, condition, outcomes in ACTION_RULES:
        key, value_match, value = condition
        specs.append({
            'name': _rule_name(project, suffix),
            'documentation': doc,
            'project': project,
            'condition_typ': 'all',
            'conditions': [_tag_condition(key, value_match, value)],
            'outcomes': _outcomes(outcomes),
            'enabled': False,
            'sort_field': sort_field,
        })
    return specs


def seed_cmk_agent_variables(project):
    """
    Create the Checkmk agent-management rule set for `project`: one base
    rule with the static config and one conditional rule per action.

    Idempotent — a rule whose name already exists is skipped, so
    re-running only fills in what is missing. Every created rule is
    disabled: adapt the values / conditions, then enable.

    Returns (created_names, skipped_names).
    """
    from .models import AnsibleCustomVariablesRule  # pylint: disable=import-outside-toplevel

    created, skipped = [], []
    for spec in _build_rule_specs(project):
        if AnsibleCustomVariablesRule.objects(name=spec['name']).first():
            skipped.append(spec['name'])
            continue
        AnsibleCustomVariablesRule(**spec).save()
        created.append(spec['name'])
    return created, skipped
