"""
Flask-Admin view for the shared NotificationChannel model.

Same collection + same view in OSS and Enterprise — Enterprise only
registers additional channel types, it does not bring its own UI.
"""
from flask_admin.form import rules
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_login import current_user

from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


class NotificationChannelView(DefaultModelView):
    """Delivery channels (email in OSS; Slack / Teams / webhook with Enterprise)."""
    column_list = ('name', 'type', 'enabled', 'description')
    column_sortable_list = ('name', 'type', 'enabled')
    column_filters = (FilterLike('name', 'Name'),
                      BooleanEqualFilter('enabled', 'Enabled'))
    column_editable_list = ['enabled']

    form_rules = modern_form(
        section('1', 'main', 'General',
                'Identity, channel type and activation. Email is '
                'handled natively via the syncer\'s Flask-Mail config; '
                'Slack / Teams / webhook delegate to the Enterprise '
                'notifications module when licensed and fall back to '
                'email delivery to the contact otherwise.',
                [rules.Field('name'),
                 rules.Field('type'),
                 rules.Field('enabled'),
                 rules.Field('description')]),
        section('2', 'cond', 'Email',
                'Only used when type = email. Override recipients '
                'explicitly (comma-separated) or leave empty to '
                'deliver to each matching contact\'s own email address.',
                [rules.Field('email_recipients'),
                 rules.Field('email_subject_prefix')]),
        section('3', 'out', 'Slack / Teams / Webhook',
                'Only used for the non-email types. The generic '
                'webhook signs the body with HMAC-SHA256 using the '
                'named Account\'s password as the secret.',
                [rules.Field('webhook_url'),
                 rules.Field('signing_secret_account'),
                 rules.Field('slack_channel'),
                 rules.Field('slack_mention'),
                 rules.Field('extra_headers')]),
    )

    form_widget_args = {
        'webhook_url': {
            'placeholder': 'Slack/Teams incoming-webhook URL or your own HTTPS endpoint',
        },
        'signing_secret_account': {
            'placeholder': 'Account whose password is the HMAC secret (generic webhook only)',
        },
        'slack_channel': {'placeholder': 'Override #channel (optional, Slack only)'},
        'slack_mention': {'placeholder': '<!here>, @netops, <!subteam^Sxxx> (optional)'},
        'email_recipients': {'placeholder': 'alice@example.com, ops@example.com'},
        'email_subject_prefix': {'placeholder': '[CMDBsyncer]'},
    }

    def is_accessible(self):
        return (current_user.is_authenticated
                and (current_user.has_right('account')
                     or current_user.global_admin))
