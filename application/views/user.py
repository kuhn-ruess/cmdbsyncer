"""
Models for flask_admin
"""
#pylint: disable=no-member
#pylint: disable=missing-function-docstring
#pylint: disable=no-self-use
from datetime import datetime
from wtforms import PasswordField
from flask_login import current_user
from application.views.default import DefaultModelView


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
