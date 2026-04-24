"""
Flask-Admin view for the shared NotificationRule model.

Same model + view in OSS and Enterprise — the Enterprise dispatcher
just consumes what operators configure here.
"""
from flask_admin.form import rules
from flask_login import current_user

from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


class NotificationRuleView(DefaultModelView):
    """Event → channel routing rules."""
    column_list = ('name', 'priority', 'enabled', 'event_type_match',
                   'severity_min', 'channels')
    column_sortable_list = ('name', 'priority', 'enabled', 'severity_min')
    column_filters = ('enabled', 'severity_min')
    column_editable_list = ['enabled', 'priority']

    form_rules = modern_form(
        section('1', 'main', 'General',
                'Name, evaluation order, activation and whether later '
                'rules still fire after this one matches.',
                [rules.Field('name'),
                 rules.Field('enabled'),
                 rules.Field('priority'),
                 rules.Field('continue_after_match')]),
        section('2', 'cond', 'Matchers',
                'Regex matchers that decide whether this rule applies '
                'to an event. Empty = any.',
                [rules.Field('event_type_match'),
                 rules.Field('severity_min'),
                 rules.Field('source_match'),
                 rules.Field('target_match'),
                 rules.Field('outcome_match')]),
        section('3', 'out', 'Channels & Message',
                'Channels that receive the event, plus Jinja templates '
                'for title and body. Templates and delivery run inside '
                'the Enterprise notifications feature — without a '
                'license, rules are stored but don\'t fire.',
                [rules.Field('channels'),
                 rules.Field('title_template'),
                 rules.Field('message_template')]),
        section('4', 'aux', 'Rate limits',
                'Cooldown per dedup key and hourly cap to avoid '
                'flooding a channel (Enterprise dispatcher).',
                [rules.Field('cooldown_minutes'),
                 rules.Field('max_per_hour')]),
    )

    form_widget_args = {
        'event_type_match': {'placeholder': 'regex, e.g. ^cron\\.group\\.'},
        'source_match': {'placeholder': 'regex, e.g. ^cron$|^audit$'},
        'target_match': {'placeholder': 'regex on target name'},
        'outcome_match': {'placeholder': '"failure" to alert only on failures'},
        'title_template': {
            'placeholder': 'Jinja: e.g. {{ title }} on {{ target }}',
            'rows': 2,
        },
        'message_template': {
            'placeholder': (
                'Jinja: e.g. {{ message }}\\n'
                '{% for k, v in details.items() %}{{k}}: {{v}}\\n{% endfor %}'
            ),
            'rows': 4,
        },
        'cooldown_minutes': {
            'placeholder': 'minutes between same-dedup-key sends (default 5)',
        },
        'max_per_hour': {
            'placeholder': 'hard cap per rule per hour (default 20)',
        },
    }

    def is_accessible(self):
        return (current_user.is_authenticated
                and (current_user.has_right('account')
                     or current_user.global_admin))
