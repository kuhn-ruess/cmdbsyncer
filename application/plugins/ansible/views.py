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

from application.modules.rule.views import (
    FiltereModelView,
    RewriteAttributeView,
    RuleModelView,
    _modern_rule_form,
    div_close,
    div_open,
)
from application.views.default import DefaultModelView

from .models import (
    AnsibleCustomVariablesRule,
    AnsibleFilterRule,
    AnsiblePlaybookFireRule,
    AnsibleProject,
    AnsibleRewriteAttributesRule,
)
from .runner import _ansible_dir, available_playbooks, run_playbook


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
        return self.render(
            'admin/ansible_project_detail.html',
            project=project,
            sections=[
                {
                    'title': 'Filter Rules',
                    'description': 'Whitelist, blacklist, and ignored hosts.',
                    'icon': 'fa-filter',
                    'endpoint': 'ansiblefilterrule',
                    'rules': AnsibleFilterRule.objects(
                        project=project,
                    ).order_by('sort_field', 'name'),
                },
                {
                    'title': 'Rewrite Attributes',
                    'description': 'Rename or reformat host attributes.',
                    'icon': 'fa-exchange',
                    'endpoint': 'ansiblerewriteattributesrule',
                    'rules': AnsibleRewriteAttributesRule.objects(
                        project=project,
                    ).order_by('sort_field', 'name'),
                },
                {
                    'title': 'Ansible Attributes',
                    'description': 'Custom variables passed to playbooks.',
                    'icon': 'fa-tags',
                    'endpoint': 'ansiblecustomvariablesrule',
                    'rules': AnsibleCustomVariablesRule.objects(
                        project=project,
                    ).order_by('sort_field', 'name'),
                },
                {
                    'title': 'Playbook Fire Rules',
                    'description': 'Auto-dispatch playbooks for matching hosts.',
                    'icon': 'fa-bolt',
                    'endpoint': 'ansibleplaybookfirerule',
                    'rules': AnsiblePlaybookFireRule.objects(
                        project=project,
                    ).order_by('sort_field', 'name'),
                },
            ],
        )

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
                },
                'form_args': {
                    'playbook': {
                        'choices': _playbook_choices,
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
        return self.render(
            'admin/ansible_playbook_run.html',
            playbooks=available_playbooks(),
            ansible_dir=str(_ansible_dir()),
        )

    @expose('/run', methods=('POST',))
    def run(self):
        """Validate the requested playbook and kick off a background run."""
        playbook = (request.form.get('playbook') or '').strip()
        target_host = (request.form.get('target_host') or '').strip() or None
        extra_vars = (request.form.get('extra_vars') or '').strip() or None
        mode = (request.form.get('mode') or 'run').strip()
        check_mode = mode == 'check'

        if playbook not in available_playbooks():
            flash(f'Unknown playbook: {playbook!r}', 'error')
            return redirect(url_for('.index'))

        stats = run_playbook(
            playbook,
            target_host=target_host,
            extra_vars=extra_vars,
            check_mode=check_mode,
            source='ui',
            triggered_by=current_user.email if current_user.is_authenticated else None,
        )
        flash(f'{"Preview" if check_mode else "Run"} started: {playbook}', 'success')
        return redirect(url_for('ansiblerunstats.details_view', id=str(stats.pk)))
