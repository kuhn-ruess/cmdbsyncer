"""
Models for flask_admin
"""
from datetime import datetime
from markupsafe import Markup, escape
from wtforms import PasswordField
from flask import flash, redirect, request, abort, url_for
from flask_admin.form import rules
from flask_admin.base import expose
from flask_wtf.csrf import generate_csrf
from flask_login import current_user
from mongoengine.errors import DoesNotExist, ValidationError

from application.models.user import User
from application.views.default import DefaultModelView
from application.views.account_select import AccountsMultiSelectField
from application.views._form_sections import modern_form, section


def _render_user_tokens(_view, _context, model, _name):
    """List a user's API tokens with a per-token revoke button (admin)."""
    if not model.api_tokens:
        return Markup('<em>none</em>')
    rows = []
    csrf = generate_csrf()
    for token in model.api_tokens:
        revoke_url = url_for('user.revoke_token_view',
                             user_id=model.id, token_id=token.token_id)
        expired = ' <span class="label label-danger">expired</span>' \
            if token.is_expired() else ''
        meta = escape(f"{token.label or 'API token'} ({token.prefix or ''}…)")
        form = (
            f'<form method="POST" action="{escape(revoke_url)}" '
            f'style="display:inline;margin-left:.4rem" '
            f"onsubmit=\"return confirm('Revoke this token?');\">"
            f'<input type="hidden" name="csrf_token" value="{escape(csrf)}">'
            f'<button class="btn btn-danger btn-xs" type="submit">Revoke</button>'
            f'</form>'
        )
        rows.append(f'<div>{meta}{expired}{form}</div>')
    return Markup(''.join(rows))


class UserView(DefaultModelView):
    """
    Extended Admin View for Users
    """
    column_sortable_list = ("email", "global_admin")
    column_exclude_list = ("pwdhash", 'tfa_secret',
                           'force_password_change', 'date_changed', 'date_password')
    # api_tokens are managed self-service (plaintext is only ever shown to the
    # owner); admins may list and revoke but never edit them in the form.
    form_excluded_columns = ("pwdhash", "api_tokens")

    column_formatters = {
        'api_tokens': _render_user_tokens,
    }
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

    # Populated in ``scaffold_form`` from the theme registry — declared
    # here so the attribute exists even when the parent view leaves it
    # undefined (Flask-Admin only sets it on its own BaseModelView).
    form_choices = {}

    form_rules = modern_form(
        section('1', 'main', 'Identity',
                'Display name and login email. The email is the primary '
                'key and is always stored lower-case.',
                [rules.Field('name'),
                 rules.Field('email')]),
        section('2', 'cond', 'Access',
                'Role grants for the admin UI and API. Global admin '
                'overrides every per-section role. Leave "Restrict to '
                'accounts" empty for full access, or pick accounts to '
                'limit this user to hosts of those accounts — both in the '
                'REST API and in the Host and Objects lists.',
                [rules.Field('global_admin'),
                 rules.Field('disabled'),
                 rules.Field('roles'),
                 rules.Field('api_roles'),
                 rules.Field('restrict_to_accounts')]),
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
        section('4', 'aux', 'Preferences',
                'Personal UI preferences. Users can also change their '
                'own theme under Account → Theme.',
                [rules.Field('theme')]),
    )

    form_overrides = {
        'restrict_to_accounts': AccountsMultiSelectField,
    }

    form_widget_args = {
        'date_added': {'disabled': True},
        'date_changed': {'disabled': True},
        'date_password': {'disabled': True},
        'last_login': {'disabled': True},
        # Render the role pickers as Select2 chip multiselects. The default
        # scaffolded ``<select multiple>`` needs Ctrl/Cmd-click and is barely
        # usable (and near-invisible on the dark themes); ``data-role=select2``
        # lets Flask-Admin's bundled JS enhance them like the account picker.
        'roles': {'data-role': 'select2'},
        'api_roles': {'data-role': 'select2'},
    }

    def scaffold_form(self):
        # pylint: disable=import-outside-toplevel
        from application.themes_registry import get_choices as theme_choices
        self.form_choices = dict(self.form_choices or {})
        self.form_choices.setdefault('theme', theme_choices())
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

    @expose('/revoke-token/<user_id>/<token_id>', methods=['POST'])
    def revoke_token_view(self, user_id, token_id):
        """Revoke another user's API token (admins only)."""
        if not self.is_accessible():
            abort(403)
        try:
            user = User.objects.get(id=user_id)
        except (DoesNotExist, ValidationError):
            flash('User not found', 'danger')
            return redirect(self.get_url('.index_view'))
        if user.revoke_api_token(token_id):
            user.save()
            flash('API token revoked.', 'success')
        else:
            flash('Token not found.', 'danger')
        return redirect(request.referrer or self.get_url('.index_view'))
