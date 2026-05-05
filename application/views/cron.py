"""
Cron Model View
"""
from datetime import datetime
from flask import flash
from flask_admin.actions import action
from flask_admin.form import rules
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import BooleanField, HiddenField

from application.views.default import DefaultModelView, name_and_enabled_filters
from application.views._form_sections import modern_form, section

def format_error_flag(_v, _c, m, _p):
    """
    Format Has error flag"
    """
    if m.failure:
        return Markup('<span style="color:red;" class="fa fa-warning"></span>')
    return Markup('<span style="color:green;" class="fa fa-circle"></span>')


def format_date(_v, _c, m, p):
    """ Format Date Field"""
    if value := getattr(m, p):
        return datetime.strftime(value, "%d.%m.%Y %H:%M")
    return ""

def _render_interval(_view, _context, model, _name):
    """
    Render Interval
    """
    if model.interval == '10min':
        return "15 Minutes"
    if model.interval == 'hour':
        return "Hourly"
    if model.interval == 'daily':
        return "Daily"
    return "Unknown"

def _render_cronjob(_view, _context, model, _name):
    """
    Render BI Rule
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.jobs):
        account = entry['account'] or ''
        html += f"<tr><td>{idx}</td><td>{escape(entry['name'])}</td>"\
                f"<td>{escape(entry['command'])}</td><td>{escape(account)}</td></tr>"
    html += "</table>"
    return Markup(html)


def _format_protected(_v, _c, m, _p):
    """Show a lock badge for protected groups."""
    if m.protected:
        return Markup(
            '<span class="badge" style="background:#7f8c8d;color:#fff;" '
            'title="Auto-managed by another feature; cannot be deleted '
            'directly.">'
            '<i class="fa fa-lock"></i> managed</span>'
        )
    return ''

class CronGroupView(DefaultModelView):
    """
    Cron Group View
    """

    column_default_sort = ("sort_field", False)

    column_sortable_list = (
        'name',
        'sort_field',
        'timerange_from',
        'timerange_to',
        'interval',
        'enabled'
    )

    column_labels = {
        'render_jobs': "Cronjobs",
        'protected': "Managed",
    }

    column_filters = name_and_enabled_filters()

    column_editable_list = [
        'enabled',
        'run_once_next',
        'continue_on_error',
        'webhook_enabled',
    ]

    column_formatters = {
        'render_jobs': _render_cronjob,
        'interval': _render_interval,
        'protected': _format_protected,
    }

    form_overrides = {
        'render_jobs': HiddenField,
        'protected': HiddenField,
    }

    column_exclude_list = ('jobs', 'webhook_token', 'webhook_token_hash')
    form_excluded_columns = ('webhook_token', 'webhook_token_hash')

    # Non-model checkbox: when ticked, on_model_change rotates the
    # token and flashes the new plaintext (the only place the operator
    # ever sees it). The hash itself stays out of the form entirely.
    form_extra_fields = {
        'rotate_webhook_token': BooleanField(
            'Regenerate webhook token on save',
            description='Tick this and save to rotate the token. '
                        'The new plaintext is shown ONCE in a flash '
                        'message — copy it then; it cannot be retrieved '
                        'later. Existing URLs using the old token stop '
                        'working immediately.',
        ),
    }

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name, evaluation order and activation.',
                [rules.Field('name'),
                 rules.Field('sort_field'),
                 rules.Field('enabled')]),
        section('2', 'cond', 'Schedule',
                'When should this group run? Interval, custom minutes and '
                'time-of-day window.',
                [rules.Field('interval'),
                 rules.Field('custom_interval_in_minutes'),
                 rules.Field('timerange_from'),
                 rules.Field('timerange_to'),
                 rules.Field('run_once_next')]),
        section('3', 'out', 'Jobs',
                'Ordered list of tasks that run as part of this group.',
                [rules.Field('jobs'),
                 rules.Field('continue_on_error')]),
        section('4', 'aux', 'Webhook Trigger',
                'External systems can trigger this group via HTTPS POST. '
                'A token is auto-generated on first enable and shown ONCE '
                'in a flash message — copy it then; the DB only keeps a '
                'SHA-256 hash, so the plaintext is not retrievable later. '
                'To rotate, tick the regenerate checkbox and save (or use '
                'the "Regenerate Webhook Token" bulk action).',
                [rules.Field('webhook_enabled'),
                 rules.Field('rotate_webhook_token')]),
    )

    form_subdocuments = {
        'jobs': {
            'form_subdocuments': {
                '': {
                    'form_rules': [
                        rules.HTML('<div class="form-row" '
                                   'style="gap: 8px; align-items: end; '
                                   'margin: 0;">'),
                        rules.HTML('<div class="col">'),
                        rules.Field('name'),
                        rules.HTML('</div>'),
                        rules.HTML('<div class="col">'),
                        rules.Field('command'),
                        rules.HTML('</div>'),
                        rules.HTML('<div class="col">'),
                        rules.Field('account'),
                        rules.HTML('</div>'),
                        rules.HTML('</div>'),
                    ],
                },
            },
        },
    }

    def on_model_change(self, form, model, is_created):
        """Allocate or rotate the webhook token. Plaintext is flashed
        once because the DB only keeps the SHA-256 hash — there is no
        way to show it again later. New groups: ensure_webhook_token
        generates on first enable. Existing groups: the operator ticks
        the `rotate_webhook_token` checkbox to force regeneration."""
        plaintext = None
        rotate = bool(getattr(form, 'rotate_webhook_token', None)
                      and form.rotate_webhook_token.data)
        if rotate and model.webhook_enabled:
            plaintext = model.regenerate_webhook_token()
        else:
            plaintext = model.ensure_webhook_token()
        if plaintext:
            flash(
                Markup(
                    'Webhook token for '
                    f'<strong>{escape(model.name)}</strong>. '
                    'Copy it now — it will not be shown again:<br>'
                    f'<code style="word-break:break-all;">{escape(plaintext)}</code>'
                ),
                'success',
            )
        return super().on_model_change(form, model, is_created)

    def delete_model(self, model):
        """Skip protected CronGroups and surface a friendly flash."""
        if getattr(model, 'protected', False):
            flash(
                f"\"{model.name}\" is managed automatically and cannot "
                f"be deleted here. Disable it instead, or remove the "
                f"owning record (e.g. the matching Backup Config).",
                'warning',
            )
            return False
        return super().delete_model(model)

    @action('regenerate_webhook_token',
            'Regenerate Webhook Token',
            'Rotate the webhook token? Existing URLs using the old token '
            'will stop working immediately.')
    def action_regenerate_webhook_token(self, ids):
        """Rotate per-group webhook tokens for the selected groups.

        The DB only stores SHA-256 hashes, so each new plaintext is
        flashed once here — there is no later way to retrieve it."""
        from application.models.cron import CronGroup  # pylint: disable=import-outside-toplevel
        for group in CronGroup.objects(id__in=ids):
            plaintext = group.regenerate_webhook_token()
            group.webhook_enabled = True
            group.save()
            flash(
                Markup(
                    f'New webhook token for <strong>{escape(group.name)}</strong> '
                    '(copy now — not retrievable later):<br>'
                    f'<code style="word-break:break-all;">{escape(plaintext)}</code>'
                ),
                'success',
            )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')



class CronStatsView(DefaultModelView):
    """
    Cron Stats Model
    """
    can_edit = False
    can_create = False
    can_export = True

    column_extra_row_actions = [] # Overwrite because of clone icon

    export_types = ['xlsx', 'csv']

    column_default_sort = ("group", True), ("next_run", True)

    column_sortable_list = (
        'group',
        'next_run',
        'last_start',
        'last_ended',
        'last_success_at',
        'failure',
    )

    page_size = 50

    column_formatters = {
        'next_run': format_date,
        'last_run': format_date,
        'last_start': format_date,
        'last_ended': format_date,
        'last_success_at': format_date,
        'failure': format_error_flag,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
