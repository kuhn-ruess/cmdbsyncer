"""
Ansible Rule Views
"""
from datetime import datetime

from flask import abort, flash, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_admin.contrib.mongoengine.filters import FilterEqual, FilterLike
from flask_admin.form import rules as form_rules
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import SelectField
from wtforms.validators import Regexp

from application.modules.inventory import list_inventory_providers
from application.modules.rule.views import (
    FiltereModelView,
    RewriteAttributeView,
    RuleModelView,
    _modern_rule_form,
    div_close,
    div_open,
)
from application.views.default import DefaultModelView

from application.modules.rule.models import (
    condition_types,
    filter_actions,
    rule_types,
)

from .models import (
    AnsibleCustomVariablesRule,
    AnsibleFilterRule,
    AnsiblePlaybookFireRule,
    AnsibleProject,
    AnsibleRewriteAttributesRule,
    AnsibleRunStats,
)
from .seed import SEED_TEMPLATES, seed_project
from .runner import (
    _ansible_dir,
    available_playbooks,
    cancel_run,
    playbook_inventory_provider,
    run_playbook,
)


# Compact match-operator labels for the project overview chips — the full
# condition_types labels ("Contains - Is the given string…") are far too
# long to sit inside a table cell.
_SHORT_MATCH = {
    'equal': '=',
    'in': 'contains',
    'not_in': 'not contains',
    'in_list': 'in list',
    'string_in_list': 'in list',
    'ewith': 'ends with',
    'swith': 'starts with',
    'regex': 'regex',
    'bool': 'is',
    'ignore': 'any',
}

# Bootstrap badge colour per condition type, mirrored from the rule list
# view so the project overview reads the same.
_CONDITION_TYP_CSS = {
    'all': 'success',
    'any': 'warning',
    'anyway': 'secondary',
}

# How many outcome chips to show before collapsing into a "+N more" note.
_MAX_OUTCOME_CHIPS = 12

# Ansible rule kinds → (model, Flask-Admin list endpoint). Drives the
# project overview sections and the inline enable/disable + delete actions,
# so all four rule types stay in sync from one place.
_RULE_KINDS = {
    'filter': (AnsibleFilterRule, 'ansiblefilterrule'),
    'rewrite': (AnsibleRewriteAttributesRule, 'ansiblerewriteattributesrule'),
    'customvars': (AnsibleCustomVariablesRule, 'ansiblecustomvariablesrule'),
    'playbook': (AnsiblePlaybookFireRule, 'ansibleplaybookfirerule'),
}


def _short_match(match_key):
    """Compact label for a condition match operator, falling back to the
    full label then the raw key."""
    return _SHORT_MATCH.get(match_key) or dict(condition_types).get(match_key, match_key)


def _summarize_conditions(rule):
    """
    Build a compact, template-friendly view of a rule's conditions:
    the condition-type badge plus one chip per condition
    (`key`, `match`, `value`). Hostname conditions render with a
    'Hostname' key so the overview reads uniformly.
    """
    chips = []
    for cond in rule.conditions:
        if cond.match_type == 'host':
            negate = cond.hostname_match_negate
            chips.append({
                'key': 'Hostname',
                'match': ('not ' if negate else '') + _short_match(cond.hostname_match),
                'value': cond.hostname or '',
            })
        else:
            negate = cond.value_match_negate
            chips.append({
                'key': cond.tag or '',
                'match': ('not ' if negate else '') + _short_match(cond.value_match),
                'value': cond.value or '',
            })
    # NB: key must not be 'items' — Jinja would resolve dict.items to the
    # method, not this value.
    return {
        'typ': dict(rule_types).get(rule.condition_typ, rule.condition_typ or ''),
        'typ_css': _CONDITION_TYP_CSS.get(rule.condition_typ, 'secondary'),
        'chips': chips,
    }


def _summarize_outcomes(rule, kind):
    """
    Return a list of short outcome strings for `rule`, shaped per rule
    `kind` (customvars / filter / rewrite / playbook), capped so a rule
    with many outcomes (e.g. the seeded base-config rule) stays compact.
    """
    labels = []
    if kind == 'customvars':
        labels = [f"{o.attribute_name} = {o.attribute_value}" for o in rule.outcomes]
    elif kind == 'filter':
        action_labels = dict(filter_actions)
        for out in rule.outcomes:
            action = action_labels.get(out.action, out.action or '')
            labels.append(f"{action}: {out.attribute_name}" if out.attribute_name else action)
    elif kind == 'rewrite':
        for out in rule.outcomes:
            target = out.new_attribute_name or out.old_attribute_name or ''
            value = out.new_value
            labels.append(f"{target} → {value}" if value else (target or '(rewrite)'))
    elif kind == 'playbook':
        for out in rule.outcomes:
            suffix = f" @ {out.inventory}" if out.inventory else ''
            labels.append(f"{out.playbook}{suffix}")
    labels = [label for label in labels if label]
    overflow = max(0, len(labels) - _MAX_OUTCOME_CHIPS)
    return labels[:_MAX_OUTCOME_CHIPS], overflow


def _ansible_main_fields():
    """Standard 'main' card for Ansible rule editors: like the base
    RuleModelView but with a Project picker between documentation and
    the enabled/last_match toggles."""
    return [
        form_rules.Field('name'),
        form_rules.Field('documentation'),
        form_rules.Field('project'),
        div_open,
        form_rules.NestedRule(('enabled', 'last_match')),
        div_close,
        form_rules.Field('sort_field'),
    ]


# Shared list template that injects project-name banner rows whenever
# the sort key is `project`. Used by all four Ansible rule list views
# so the table looks like one section per project instead of one giant
# flat row stream.
ANSIBLE_RULE_LIST_TEMPLATE = 'admin/ansible_rule_list.html'

# Default sort that keeps rules grouped by project (Default first, since
# its sort_field=-1) and ordered by sort_field within each project.
ANSIBLE_RULE_DEFAULT_SORT = 'project'


def _format_project(_v, _c, m, _p):
    """Render the project reference as its name, dim if unset."""
    if m.project:
        return Markup(f'<span class="badge badge-info">{escape(m.project.name)}</span>')
    return Markup('<span class="text-muted">—</span>')


def _playbook_choices():
    """
    Build the SelectField choices from the same discovery used by the
    Run Playbook UI so the two stay in sync. Choice value = filename
    (what the runner needs); choice label = the manifest's friendly name.
    """
    return list(available_playbooks().items())


def _provider_choices_with_blank():
    """Inventory provider choices for the fire-rule outcome dropdown.
    Empty value means 'use the playbook manifest's default'."""
    return [('', '— manifest default —')] + [
        (p, p) for p in list_inventory_providers()
    ]


def _format_project_name_link(_view, _context, model, _name):
    """Render the project name as a link to the project detail page,
    where the user manages all four rule types for that project in one
    spot."""
    href = url_for('ansibleproject.project_detail', project_id=str(model.pk))
    return Markup(
        f'<a href="{escape(href)}" style="font-weight:600;">'
        f'{escape(model.name)}</a>'
    )


class AnsibleProjectView(DefaultModelView):
    """
    CRUD for AnsibleProject. Each enabled project is exposed as its own
    inventory provider — see Modules → Ansible → Inventory Providers.
    """

    column_default_sort = ('sort_field', False)
    column_list = ('name', 'description', 'enabled', 'sort_field')
    column_sortable_list = ('name', 'enabled', 'sort_field')
    column_editable_list = ('enabled', 'sort_field')
    column_filters = (
        FilterLike('name', 'Name'),
    )

    column_formatters = {
        'name': _format_project_name_link,
    }

    form_columns = ('name', 'description', 'enabled', 'sort_field')

    # The provider name is the project name, so it has to survive being
    # used as a CLI argument, an env-var value, and a URL path segment.
    # Reject spaces and friends at form-validate time so the user sees a
    # red field instead of a 500 from the model's clean() defence layer.
    form_args = {
        'name': {
            'validators': [
                Regexp(
                    r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$',
                    message=(
                        "Name must start with a letter or digit and use only "
                        "letters, digits, '_', '.' and '-' — no spaces."
                    ),
                ),
            ],
        },
    }

    @expose('/details/<project_id>')
    def project_detail(self, project_id):
        """
        Project workspace: lists every Ansible rule (Filter, Rewrite,
        Custom Variables, Playbook Fire) that belongs to this project,
        plus '+ New' shortcuts that drop the user into the matching
        rule editor with the project pre-selected and a return-url back
        here so save / cancel land on this page.
        """
        project = AnsibleProject.objects(id=project_id).first()
        if project is None:
            abort(404)

        # (title, description, icon, kind). The kind resolves to the model
        # and list endpoint via _RULE_KINDS and drives how each rule's
        # outcomes are summarised for the overview.
        section_specs = [
            ('Filter Rules', 'Whitelist, blacklist, and ignored hosts.',
             'fa-filter', 'filter'),
            ('Rewrite Attributes', 'Rename or reformat host attributes.',
             'fa-exchange', 'rewrite'),
            ('Ansible Attributes', 'Custom variables passed to playbooks.',
             'fa-tags', 'customvars'),
            ('Playbook Fire Rules', 'Auto-dispatch playbooks for matching hosts.',
             'fa-bolt', 'playbook'),
        ]

        sections = []
        for title, description, icon, kind in section_specs:
            model, endpoint = _RULE_KINDS[kind]
            rules = []
            for rule in model.objects(project=project).order_by('sort_field', 'name'):
                outcomes, outcomes_overflow = _summarize_outcomes(rule, kind)
                rules.append({
                    'obj': rule,
                    'conditions': _summarize_conditions(rule),
                    'outcomes': outcomes,
                    'outcomes_overflow': outcomes_overflow,
                })
            sections.append({
                'title': title,
                'description': description,
                'icon': icon,
                'endpoint': endpoint,
                'kind': kind,
                'rules': rules,
            })

        return self.render(
            'admin/ansible_project_detail.html',
            project=project,
            sections=sections,
            seed_templates=[
                {'key': key, 'label': tpl['label']}
                for key, tpl in SEED_TEMPLATES.items()
            ],
        )

    @expose('/seed/<project_id>/<seed_key>', methods=('POST',))
    def seed_rules(self, project_id, seed_key):
        """
        One-click seed: apply the seed template `seed_key` (from the
        registry in seed.py) to this project. Idempotent — rules that
        already exist are left untouched. The registry is generic, so new
        seed templates become available here without touching this view.
        """
        project = AnsibleProject.objects(id=project_id).first()
        if project is None:
            abort(404)
        result = seed_project(project, seed_key)
        if result is None:
            flash(f"Unknown seed template: {seed_key!r}", 'error')
            return redirect(url_for('.project_detail', project_id=project_id))
        created, skipped = result
        if created:
            flash(
                f"Seeded {len(created)} rule(s). Adapt the server / credential "
                "values and the conditions, then enable the rules.",
                'success',
            )
        if skipped:
            flash(
                f"{len(skipped)} rule(s) already existed and were left "
                "unchanged.",
                'info',
            )
        return redirect(url_for('.project_detail', project_id=project_id))

    @expose('/toggle-rule/<kind>/<rule_id>', methods=('POST',))
    def toggle_rule(self, kind, rule_id):
        """
        Flip a rule's `enabled` flag straight from the project overview
        (the status badge posts here), so a rule can be activated /
        deactivated without opening its editor.
        """
        entry = _RULE_KINDS.get(kind)
        if entry is None:
            abort(404)
        model = entry[0]
        rule = model.objects(id=rule_id).first()
        if rule is None:
            abort(404)
        rule.enabled = not rule.enabled
        rule.save()
        flash(
            f"Rule '{rule.name}' {'enabled' if rule.enabled else 'disabled'}.",
            'success',
        )
        return_url = request.form.get('url') or url_for(
            '.project_detail', project_id=str(rule.project.pk) if rule.project else '',
        )
        return redirect(return_url)

    def is_accessible(self):
        """Overwrite — same right gates all Ansible config."""
        return current_user.is_authenticated and current_user.has_right('ansible')


class _ProjectAwareRuleView:  # pylint: disable=too-few-public-methods
    """
    Mixin used by every rule list view. Pre-fills the project field on
    create forms when `?project=<id>` is in the URL, so the '+ New'
    links on the project detail page drop the user into the right
    context. Together with the `?url=...` return-link Flask-Admin
    already honours, the full flow lands the user back on the project
    page after save.
    """
    def create_form(self, obj=None):
        """Inject the project from the URL into the empty create form."""
        form = super().create_form(obj=obj)  # pylint: disable=no-member
        project_id = request.args.get('project')
        if project_id and hasattr(form, 'project'):
            project = AnsibleProject.objects(id=project_id).first()
            if project:
                form.project.data = project
        return form


class AnsibleCustomVariablesView(_ProjectAwareRuleView, RuleModelView):  # pylint: disable=too-many-ancestors
    """
    Custom Rule Model View
    """


    list_template = ANSIBLE_RULE_LIST_TEMPLATE
    column_default_sort = ANSIBLE_RULE_DEFAULT_SORT

    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    column_filters = list(RuleModelView.column_filters) + [
        FilterEqual('project', 'Project'),
    ]

    column_formatters = {
        **RuleModelView.column_formatters,
        'project': _format_project,
    }

    form_rules = _modern_rule_form(
        main_fields=_ansible_main_fields(),
        condition_fields=[
            form_rules.Field('condition_typ'),
            form_rules.Field('conditions'),
        ],
        outcome_fields=[form_rules.Field('outcomes')],
        outcome_title='Outcomes',
        outcome_desc='What the rule does to matching hosts.',
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('ansible')


class AnsibleFilterRuleView(_ProjectAwareRuleView, FiltereModelView):  # pylint: disable=too-many-ancestors
    """
    Filter rule editor with project assignment.
    """

    list_template = ANSIBLE_RULE_LIST_TEMPLATE
    column_default_sort = ANSIBLE_RULE_DEFAULT_SORT

    column_filters = list(FiltereModelView.column_filters) + [
        FilterEqual('project', 'Project'),
    ]
    column_formatters = {
        **FiltereModelView.column_formatters,
        'project': _format_project,
    }

    form_rules = _modern_rule_form(
        main_fields=_ansible_main_fields(),
        condition_fields=[
            form_rules.Field('condition_typ'),
            form_rules.Field('conditions'),
        ],
        outcome_fields=[form_rules.Field('outcomes')],
        outcome_title='Filter Actions',
        outcome_desc='Which labels / attributes pass through for matching hosts.',
    )

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('ansible')


class AnsibleRewriteRuleView(_ProjectAwareRuleView, RewriteAttributeView):  # pylint: disable=too-many-ancestors
    """
    Attribute-rewrite rule editor with project assignment.
    """

    list_template = ANSIBLE_RULE_LIST_TEMPLATE
    column_default_sort = ANSIBLE_RULE_DEFAULT_SORT

    column_filters = list(RewriteAttributeView.column_filters) + [
        FilterEqual('project', 'Project'),
    ]

    form_rules = _modern_rule_form(
        main_fields=_ansible_main_fields(),
        condition_fields=[
            form_rules.Field('condition_typ'),
            form_rules.Field('conditions'),
        ],
        outcome_fields=[form_rules.Field('outcomes')],
        outcome_title='Attribute Rewrites',
        outcome_desc='Rename / reformat attributes for matching hosts.',
    )

    def __init__(self, *args, **kwargs):
        """Append the project column formatter on top of the parent's
        runtime-built formatter map."""
        super().__init__(*args, **kwargs)
        self.column_formatters['project'] = _format_project

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('ansible')


class AnsiblePlaybookFireRuleView(_ProjectAwareRuleView, RuleModelView):  # pylint: disable=too-many-ancestors
    """
    Editor for rules that fire playbooks against matching hosts.
    """

    column_exclude_list = [
        'conditions', 'outcomes', 'render_full_conditions',
        'render_playbook_outcomes',
    ]

    column_filters = list(RuleModelView.column_filters) + [
        FilterEqual('project', 'Project'),
    ]

    column_formatters = {
        **RuleModelView.column_formatters,
        'project': _format_project,
    }

    form_rules = _modern_rule_form(
        main_fields=_ansible_main_fields(),
        condition_fields=[
            form_rules.Field('condition_typ'),
            form_rules.Field('conditions'),
        ],
        outcome_fields=[form_rules.Field('outcomes')],
        outcome_title='Playbook Fires',
        outcome_desc='Which playbook(s) to run against matching hosts.',
    )

    form_subdocuments = dict(RuleModelView.form_subdocuments)
    form_subdocuments['outcomes'] = {
        'form_subdocuments': {
            '': {
                'form_overrides': {
                    'playbook': SelectField,
                    'inventory': SelectField,
                },
                'form_args': {
                    'playbook': {
                        'choices': _playbook_choices,
                    },
                    'inventory': {
                        'choices': _provider_choices_with_blank,
                    },
                },
            },
        },
    }

    def is_accessible(self):
        """Overwrite — same right gates the rules views."""
        return current_user.is_authenticated and current_user.has_right('ansible')


def _format_status(_v, _c, m, _p):
    """Color-code run status."""
    color = {
        'running': '#888',
        'success': 'green',
        'failure': 'red',
        'cancelled': '#d97706',
    }.get(m.status, '#888')
    label = (m.status or 'unknown').capitalize()
    return Markup(f'<span style="color:{color};font-weight:600;">{escape(label)}</span>')


def _format_date(_v, _c, m, p):
    """Format datetime fields."""
    if value := getattr(m, p, None):
        return datetime.strftime(value, "%d.%m.%Y %H:%M:%S")
    return ""


def _format_log(_v, _c, m, _p):
    """Render the log inline as a fixed-height scrollable pre block."""
    text = m.log or ""
    if not text:
        return ""
    return Markup(
        '<pre style="max-height:240px;overflow:auto;background:#111;'
        'color:#ddd;padding:8px;border-radius:4px;font-size:11px;'
        f'white-space:pre-wrap;">{escape(text)}</pre>'
    )


class AnsibleRunStatsView(DefaultModelView):
    """
    Read-only history of playbook runs (UI / rule / CLI triggered).
    Mirrors the CronStats pattern — runs are append-only audit records.
    """
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True

    column_extra_row_actions = []  # Drop the clone icon for stats rows
    export_types = ['xlsx', 'csv']

    page_size = 50

    column_default_sort = ('started_at', True)

    column_list = (
        'playbook',
        'target_host',
        'mode',
        'source',
        'triggered_by',
        'started_at',
        'ended_at',
        'status',
        'exit_code',
    )

    column_sortable_list = (
        'playbook',
        'target_host',
        'mode',
        'source',
        'triggered_by',
        'started_at',
        'ended_at',
        'status',
        'exit_code',
    )

    column_filters = (
        FilterLike('playbook', 'Playbook'),
        FilterLike('target_host', 'Host'),
        FilterEqual('status', 'Status', options=[
            ('running', 'Running'),
            ('success', 'Success'),
            ('failure', 'Failure'),
            ('cancelled', 'Cancelled'),
        ]),
        FilterEqual('mode', 'Mode', options=[
            ('run', 'Run'),
            ('check', 'Preview'),
        ]),
        FilterEqual('source', 'Source', options=[
            ('ui', 'UI'),
            ('rule', 'Rule'),
            ('cli', 'CLI'),
        ]),
    )

    column_formatters = {
        'started_at': _format_date,
        'ended_at': _format_date,
        'status': _format_status,
    }

    column_details_list = (
        'playbook',
        'target_host',
        'extra_vars',
        'mode',
        'source',
        'triggered_by',
        'started_at',
        'ended_at',
        'status',
        'exit_code',
        'pid',
        'log',
    )

    column_formatters_detail = {
        'started_at': _format_date,
        'ended_at': _format_date,
        'status': _format_status,
        'log': _format_log,
    }

    can_view_details = True
    # Auto-reloads the detail page while the run is still 'running' so the
    # log and final status appear without a manual refresh.
    details_template = 'admin/ansible_run_details.html'

    @expose('/cancel/<run_id>', methods=('POST',))
    def cancel(self, run_id):
        """Stop a still-running playbook (the detail page's Cancel button)."""
        stats = AnsibleRunStats.objects(id=run_id).first()
        if stats is None:
            abort(404)
        if cancel_run(stats):
            flash(f"Cancellation requested for '{stats.playbook}'.", 'success')
        else:
            flash('Run is not running — nothing to cancel.', 'info')
        return redirect(url_for('.details_view', id=run_id))

    def is_accessible(self):
        """Overwrite — same right gates the rules views."""
        return current_user.is_authenticated and current_user.has_right('ansible')


class AnsiblePlaybookRunView(BaseView):
    """
    Lists bundled playbooks with a Run button and dispatches into the
    background runner. The actual run history lives in AnsibleRunStatsView.
    """

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('ansible')

    @expose('/')
    def index(self):
        """Render the list of available playbooks with run controls."""
        playbook_entries = [
            {
                'file': file_name,
                'name': display_name,
                'default_provider': playbook_inventory_provider(file_name),
            }
            for file_name, display_name in available_playbooks().items()
        ]
        return self.render(
            'admin/ansible_playbook_run.html',
            playbooks=playbook_entries,
            providers=list_inventory_providers(),
            ansible_dir=str(_ansible_dir()),
        )

    @expose('/run', methods=('POST',))
    def run(self):
        """Validate the requested playbook and kick off a background run."""
        playbook = (request.form.get('playbook') or '').strip()
        target_host = (request.form.get('target_host') or '').strip() or None
        extra_vars = (request.form.get('extra_vars') or '').strip() or None
        provider = (request.form.get('provider') or '').strip() or None
        ssh_user = (request.form.get('ssh_user') or '').strip() or None
        # Password intentionally not stripped — trailing spaces could be
        # meaningful; only an all-empty field is treated as "not set".
        ssh_password = request.form.get('ssh_password') or None
        mode = (request.form.get('mode') or 'run').strip()
        check_mode = mode == 'check'

        if playbook not in available_playbooks():
            flash(f'Unknown playbook: {playbook!r}', 'error')
            return redirect(url_for('.index'))
        if provider and provider not in list_inventory_providers():
            flash(f'Unknown inventory provider: {provider!r}', 'error')
            return redirect(url_for('.index'))

        stats = run_playbook(
            playbook,
            target_host=target_host,
            extra_vars=extra_vars,
            check_mode=check_mode,
            provider=provider,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
            source='ui',
            triggered_by=current_user.email if current_user.is_authenticated else None,
        )
        flash(f'{"Preview" if check_mode else "Run"} started: {playbook}', 'success')
        return redirect(url_for('ansiblerunstats.details_view', id=str(stats.pk)))
