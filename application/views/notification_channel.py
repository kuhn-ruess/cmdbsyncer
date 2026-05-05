"""
Flask-Admin view for the shared NotificationChannel model.

Same collection + same view in OSS and Enterprise — Enterprise only
registers additional channel types, it does not bring its own UI.
"""
from flask_admin.form import rules
from flask_login import current_user

from application.views.default import DefaultModelView, name_and_enabled_filters
from application.views._form_sections import modern_form, section
from application.views._form_fields import AccountSelectField


class NotificationChannelView(DefaultModelView):
    """Delivery channels (email in OSS; Slack / Teams / webhook with Enterprise)."""
    column_list = ('name', 'type', 'enabled', 'description')
    column_sortable_list = ('name', 'type', 'enabled')
    column_filters = name_and_enabled_filters()
    column_editable_list = ['enabled']

    form_overrides = {
        'account': AccountSelectField,
    }

    form_rules = modern_form(
        section('1', 'main', 'General',
                'Identity, channel type and activation.',
                [rules.Field('name'),
                 rules.Field('type'),
                 rules.Field('enabled'),
                 rules.Field('description')]),
        section('2', 'cond', 'Delivery target',
                'Slack / Teams / webhook: pick the Syncer Account '
                'that carries the endpoint URL (Address), the optional '
                'signing secret (Password) and any per-integration '
                'details (Custom Fields). Leave empty for email — '
                'delivery runs through the Flask-Mail config.',
                [rules.Field('account')]),
        section('3', 'out', 'Email',
                'Only used when type = email. Override recipients '
                'explicitly (comma-separated) or leave empty to '
                'deliver to each matching contact\'s own email address.',
                [rules.Field('email_recipients'),
                 rules.Field('email_subject_prefix')]),
    )

    form_widget_args = {
        'email_recipients': {'placeholder': 'alice@example.com, ops@example.com'},
        'email_subject_prefix': {'placeholder': '[CMDBsyncer]'},
    }

    def is_accessible(self):
        return (current_user.is_authenticated
                and (current_user.has_right('account')
                     or current_user.global_admin))
