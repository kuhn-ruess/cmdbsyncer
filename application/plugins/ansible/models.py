"""
Ansible Rule
"""
# pylint: disable=too-few-public-methods
import re

from mongoengine.errors import ValidationError

from application import db
from application.modules.inventory import is_reserved_provider_name
from application.modules.rule.models import rule_types

_PROJECT_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$')

DEFAULT_PROJECT_NAME = 'Default'


class AnsibleProject(db.Document):
    """
    A project groups Ansible rules into an isolated rule source.

    Each enabled project is exposed as its own inventory provider
    (named after the project) — that's how a playbook can pick a
    rule source via the manifest's `inventory:` field. Rules without
    a project are served by the default `ansible` provider, which is
    the legacy / global behaviour.
    """
    name = db.StringField(required=True, unique=True)
    description = db.StringField()
    enabled = db.BooleanField(default=True)
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }

    def clean(self):
        """Reject names that would collide with statically registered
        providers (e.g. `ansible`, `cmk_sites`) or break URL routing."""
        name = (self.name or '').strip()
        if not _PROJECT_NAME_RE.match(name):
            raise ValidationError(
                "Project name must start with a letter or digit and use "
                "only letters, digits, '_', '.', '-'."
            )
        if is_reserved_provider_name(name):
            raise ValidationError(
                f"Project name '{name}' collides with a built-in inventory "
                "provider. Pick a different name."
            )
        self.name = name

    def __str__(self):
        """Used by Flask-Admin's QuerySelectField when rendering project
        dropdowns on rule editors — without this the dropdown would show
        `AnsibleProject Object` instead of the project name."""
        return self.name or super().__str__()


def ensure_default_project():
    """
    Create the auto-managed Default project on first run and assign any
    rule that still has `project=None` (legacy global rules) to it.

    The Default project is what every newly created rule's editor
    pre-selects, and it is what the static `ansible` provider serves —
    so existing manifest entries with `inventory: ansible` keep working
    while the rules themselves now live inside a project, ready to be
    grouped in the UI.

    Idempotent: re-running has no effect once migration is complete.
    Returns the Default project document.
    """
    default = AnsibleProject.objects(name=DEFAULT_PROJECT_NAME).first()
    if default is None:
        default = AnsibleProject(
            name=DEFAULT_PROJECT_NAME,
            description=(
                "Auto-managed project for rules that were created before "
                "the Project feature existed, and the default for newly "
                "created rules."
            ),
            enabled=True,
            sort_field=-1,
        )
        default.save()
    for cls in (
        AnsibleCustomVariablesRule,
        AnsibleFilterRule,
        AnsibleRewriteAttributesRule,
        AnsiblePlaybookFireRule,
    ):
        cls.objects(project=None).update(project=default)
    return default

run_sources = [
    ('ui', 'UI'),
    ('rule', 'Rule'),
    ('cli', 'CLI'),
]

run_statuses = [
    ('running', 'Running'),
    ('success', 'Success'),
    ('failure', 'Failure'),
]

run_modes = [
    ('run', 'Run'),
    ('check', 'Preview (--check --diff)'),
]


class AnsibleRunStats(db.Document):
    """
    Persisted history of `ansible-playbook` invocations triggered from the
    Syncer (UI button, rule outcome, CLI). Mirrors the read-only pattern of
    CronStats so users can review what ran, when, against which host, and
    inspect the captured log.
    """
    playbook = db.StringField(required=True)
    target_host = db.StringField()
    extra_vars = db.StringField()
    mode = db.StringField(choices=run_modes, default='run')
    source = db.StringField(choices=run_sources, default='ui')
    triggered_by = db.StringField()

    started_at = db.DateTimeField()
    ended_at = db.DateTimeField()
    status = db.StringField(choices=run_statuses, default='running')
    exit_code = db.IntField()
    pid = db.IntField()

    log = db.StringField()

    meta = {
        'strict': False,
        'indexes': ['-started_at'],
    }

class AnsibleCustomVariablesRule(db.Document):
    """
    Rules for Ansible
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    project = db.ReferenceField(
        document_type=AnsibleProject,
        required=False,
        default=lambda: AnsibleProject.objects(name=DEFAULT_PROJECT_NAME).first(),
    )

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="CustomAttribute"))
    render_attribute_outcomes = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)


    meta = {
        'strict': False
    }

#   .-- Ansible Attribute Filter
class AnsibleFilterRule(db.Document):
    """
    Filter Attributes
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    project = db.ReferenceField(
        document_type=AnsibleProject,
        required=False,
        default=lambda: AnsibleProject.objects(name=DEFAULT_PROJECT_NAME).first(),
    )
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="FilterAction"))
    render_filter_outcome = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }

#.
#   .-- Playbook Fire Outcome
class AnsiblePlaybookAction(db.EmbeddedDocument):
    """
    Outcome that fires an Ansible playbook against the matching host.
    Dedup is per (rule, host, playbook) — once a successful (or failed)
    AnsibleRunStats record exists for that triple, the rule will not fire
    again. Delete the run record to allow a re-fire.

    `inventory` is the inventory provider override; leave empty to use
    the playbook manifest's default. Useful when one rule needs to fire
    a playbook against a different rule source than the one the playbook
    declares (e.g. firing cmk_server_mngmt.yml from a host-driven rule).
    """
    playbook = db.StringField(required=True)
    inventory = db.StringField()
    extra_vars = db.StringField()

    meta = {
        'strict': False,
    }


class AnsiblePlaybookFireRule(db.Document):
    """
    Rule that triggers playbook runs for matching hosts. Matching uses
    the standard rule engine; firing is driven by the `ansible
    fire_playbook_rules` CLI / cron command rather than the inventory
    hot path so that read-only `--list` calls never start playbook runs.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    project = db.ReferenceField(
        document_type=AnsibleProject,
        required=False,
        default=lambda: AnsibleProject.objects(name=DEFAULT_PROJECT_NAME).first(),
    )

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField()  # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="AnsiblePlaybookAction"))
    render_playbook_outcomes = db.StringField()  # Helper for preview

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }
#.
#   .-- Rewrite Attributes
class AnsibleRewriteAttributesRule(db.Document):
    """
    Rule to Attributes existing Attributes
    """
    name = db.StringField()
    documentation = db.StringField()

    project = db.ReferenceField(
        document_type=AnsibleProject,
        required=False,
        default=lambda: AnsibleProject.objects(name=DEFAULT_PROJECT_NAME).first(),
    )

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="AttributeRewriteAction"))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
