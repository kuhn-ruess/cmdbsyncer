"""Flask-Admin view for the simplified NotificationRule model."""
from flask_admin.form import rules
from flask_login import current_user

from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


_PLACEHOLDER_HELP = rules.HTML(
    '<div style="margin:0 0 12px;padding:10px 12px;border:1px solid #e2e6ea;'
    'border-radius:8px;background:#f8f9fa;font-size:0.88rem;">'
    '<strong>Available Jinja variables</strong>'
    '<div style="display:grid;grid-template-columns:max-content 1fr;'
    'column-gap:14px;row-gap:4px;margin-top:6px;font-family:ui-monospace,monospace;">'
    # log source
    '<div style="grid-column:1/-1;color:#666;margin-top:2px;">'
    '<em>source_type = log</em></div>'
    '<code>{{ message }}</code><span>The log message text</span>'
    '<code>{{ source }}</code>'
    '<span>Log source — e.g. `cmk_host_sync`, `notification`, plugin source</span>'
    '<code>{{ has_error }}</code>'
    '<span>True if any of the entry\'s details was flagged as an error</span>'
    '<code>{{ details }}</code><span>Dict of `(key, value)` pairs the caller attached</span>'
    '<code>{{ affected_hosts }}</code><span>List of hostnames the call passed</span>'
    # audit source
    '<div style="grid-column:1/-1;color:#666;margin-top:8px;">'
    '<em>source_type = audit</em></div>'
    '<code>{{ event_type }}</code><span>e.g. `user.login.failure`, `account.updated`</span>'
    '<code>{{ outcome }}</code><span>`success` / `failure`</span>'
    '<code>{{ message }}</code><span>Audit message field</span>'
    '<code>{{ actor_name }}</code><span>Who triggered it</span>'
    '<code>{{ actor_ip }}</code><span>Source IP (when web-triggered)</span>'
    '<code>{{ target }}</code> / <code>target_type</code> / <code>target_id</code>'
    '<span>The affected resource</span>'
    '<code>{{ details }}</code><span>Audit metadata dict</span>'
    '<code>{{ trace_id }}</code><span>Request trace id</span>'
    '</div></div>'
)


class NotificationRuleView(DefaultModelView):
    """Route Log or Audit events to channels."""
    column_list = ('name', 'priority', 'enabled', 'source_type',
                   'only_errors', 'match_pattern', 'channels')
    column_sortable_list = ('name', 'priority', 'enabled', 'source_type')
    column_filters = ('enabled', 'source_type', 'only_errors')
    column_editable_list = ['enabled', 'priority']

    form_rules = modern_form(
        section('1', 'main', 'General',
                'Name, evaluation order and activation. All matching '
                'enabled rules fire — there is no first-match short-circuit.',
                [rules.Field('name'),
                 rules.Field('enabled'),
                 rules.Field('priority')]),
        section('2', 'cond', 'Source',
                'What kind of event triggers this rule. `log` matches '
                'every record written via the syncer Log; `audit` matches '
                'every persisted audit entry. `only_errors` (log only) '
                'restricts the rule to entries flagged as errors. '
                '`match_pattern` is an optional regex against the log '
                'message (log) or the audit event_type (audit).',
                [rules.Field('source_type'),
                 rules.Field('only_errors'),
                 rules.Field('match_pattern')]),
        section('3', 'out', 'Channels & Message',
                'Channels that receive the event, plus optional Jinja '
                'templates for title and body. Empty templates fall back '
                'to the event\'s own title / message.',
                [rules.Field('channels'),
                 _PLACEHOLDER_HELP,
                 rules.Field('title_template'),
                 rules.Field('message_template')]),
        section('4', 'aux', 'Rate limit',
                'Minutes between two notifications from the same rule '
                'for the same event key.',
                [rules.Field('cooldown_minutes')]),
    )

    form_widget_args = {
        'match_pattern': {
            'placeholder': 'optional regex, e.g. ^cron\\.|failed',
        },
        'title_template': {
            'placeholder': 'Jinja: e.g. {{ source }}: {{ message }}',
            'rows': 2,
        },
        'message_template': {
            'placeholder': 'Jinja: e.g. {{ message }}',
            'rows': 4,
        },
        'cooldown_minutes': {
            'placeholder': 'minutes between sends for the same event key',
        },
    }

    def is_accessible(self):
        return (current_user.is_authenticated
                and (current_user.has_right('account')
                     or current_user.global_admin))
