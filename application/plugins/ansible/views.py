"""
Ansible Rule Views
"""
from datetime import datetime

from flask import flash, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_admin.contrib.mongoengine.filters import FilterEqual, FilterLike
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import SelectField

from application.modules.rule.views import RuleModelView
from application.views.default import DefaultModelView

from .runner import _ansible_dir, available_playbooks, run_playbook


def _playbook_choices():
    """
    Build the SelectField choices from the same discovery used by the
    Run Playbook UI so the two stay in sync. Choice value = filename
    (what the runner needs); choice label = the manifest's friendly name.
    """
    return list(available_playbooks().items())


class AnsibleCustomVariablesView(RuleModelView):
    """
    Custom Rule Model View
    """


    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('ansible')


class AnsiblePlaybookFireRuleView(RuleModelView):
    """
    Editor for rules that fire playbooks against matching hosts.
    """

    column_exclude_list = [
        'conditions', 'outcomes', 'render_full_conditions',
        'render_playbook_outcomes',
    ]

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
