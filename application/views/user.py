"""
Models for flask_admin
"""
from datetime import datetime
from wtforms import PasswordField
from flask_admin.form import rules
from flask_login import current_user

from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


class UserView(DefaultModelView):
    """
    Extended Admin View for Users
    """
    column_sortable_list = ("email", "global_admin")
    column_exclude_list = ("pwdhash", 'tfa_secret',
                           'force_password_change', 'date_changed', 'date_password')
    form_excluded_columns = ("pwdhash", )
    page_size = 100
    can_set_page_size = True
    column_filters = (
        'email',
        'name',
        'global_admin',
    )

    column_editable_list = (
        'disabled',
    )

    form_rules = modern_form(
        section('1', 'main', 'Identity',
                'Display name and login email. The email is the primary '
                'key and is always stored lower-case.',
                [rules.Field('name'),
                 rules.Field('email')]),
        section('2', 'cond', 'Access',
                'Role grants for the admin UI and API. Global admin '
                'overrides every per-section role.',
                [rules.Field('global_admin'),
                 rules.Field('disabled'),
                 rules.Field('roles'),
                 rules.Field('api_roles')]),
        section('3', 'out', 'Credentials',
                'Password (leave blank to keep), 2FA secret and the '
                'force-change flag. Timestamps are read-only.',
                [rules.Field('password'),
                 rules.Field('tfa_secret'),
                 rules.Field('force_password_change'),
                 rules.Field('date_added'),
                 rules.Field('date_changed'),
                 rules.Field('date_password'),
                 rules.Field('last_login')]),
    )

    form_widget_args = {
        'date_added': {'disabled': True},
        'date_changed': {'disabled': True},
        'date_password': {'disabled': True},
        'last_login': {'disabled': True},
    }

    def scaffold_form(self):
        form_class = super().scaffold_form()
        form_class.password = PasswordField("Password")
        return form_class

    def on_model_change(self, form, model, is_created):
        if form.email.data:
            model.email = form.email.data.lower()
        if form.password.data:
            # Time of Password Change will stored by set_password
            model.set_password(form.password.data)
        if is_created:
            model.date_added = datetime.now()
        else:
            model.date_changed = datetime.now()
        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('user')
