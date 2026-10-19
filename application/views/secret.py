"""
Secret Store View

The former Checkmk password store, now usable by every module. Which
entries a user sees, edits, binds and reveals is decided by
``application.helpers.secret_access``; this view only asks it.
"""
# pylint: disable=no-member
from markupsafe import Markup, escape
from flask import abort, flash, make_response, redirect, request, url_for
from flask_admin import expose
from flask_admin.form import rules
from flask_admin.contrib.mongoengine.filters import FilterLike, BooleanEqualFilter
from flask_admin.model.template import EndpointLinkRowAction
from flask_login import current_user
from wtforms import PasswordField, StringField
from wtforms.validators import ValidationError

from application import logger
from application.docu_links import docu_links
from application.helpers.secret_access import (
    can_access, can_bind, can_manage, can_reveal, can_reveal_role, is_scoped,
    visible_secrets,
)
from application.models.host import Host
from application.models.secret import Secret, host_secret_name, refresh_orphans
from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


def _render_binding(_view, _context, model, _name):
    """List column: the bound host, global, or orphaned."""
    if model.host_id is None:
        return Markup('<em>global</em>')
    label = escape(model.hostname or '')
    if model.orphaned:
        return Markup(f'{label} <span class="badge badge-warning">orphaned</span>')
    return label


class SecretView(DefaultModelView):
    """
    Secret Store
    """
    # No clone: a copy of a host-bound secret is a second secret for the
    # same host and key. Instead a row action to show the value for copying.
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-eye", ".reveal_view", title="Show value"),
    ]

    column_list = ('name', 'hostname', 'key', 'kind', 'title',
                   'export_to_checkmk', 'source', 'enabled')
    column_labels = {
        'hostname': 'Bound to host',
        'export_to_checkmk': 'To Checkmk',
    }
    column_formatters = {
        'hostname': _render_binding,
    }
    column_sortable_list = ('name', 'hostname', 'key', 'kind')
    column_filters = (
        FilterLike("name", 'Name'),
        FilterLike("hostname", 'Bound to host'),
        FilterLike("key", 'Key'),
        FilterLike("title", 'Title'),
        BooleanEqualFilter("orphaned", 'Orphaned'),
    )
    column_editable_list = ['enabled']

    form_excluded_columns = [
        'password_crypted', 'host_id', 'orphaned', 'last_export_hash',
        'updated_at', 'source',
    ]
    form_overrides = {
        'hostname': StringField,
    }
    form_args = {
        'hostname': {
            'label': 'Bound to host',
            'description': "Leave empty for a global entry. With a host the "
                           "entry belongs to that host and rules reach it "
                           "with {{ secret('key') }} while rendering it. Put a "
                           "new hostname here to bind an orphaned entry to "
                           "another host.",
        },
        'key': {
            'description': "Name of the secret on the host, e.g. checkmk_token. "
                           "Required for a host-bound entry.",
        },
        'export_to_checkmk': {
            'label': 'Export to Checkmk',
            'description': "Write the entry into Checkmk's password store. "
                           "Certificates cannot be created there over the API.",
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_password_store"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Basics',
                    'Internal name, notes and activation.',
                    [rules.Field('name'),
                     rules.Field('documentation'),
                     rules.Field('enabled')]),
            section('2', 'match', 'Secret',
                    'The value, what kind it is and which host it belongs to.',
                    [rules.Field('kind'),
                     rules.Field('password'),
                     rules.Field('hostname'),
                     rules.Field('key')]),
            section('3', 'out', "Export to Checkmk",
                    'Optional: Checkmk can keep this entry in its own password '
                    'store, these fields describe it there.',
                    [rules.Field('export_to_checkmk'),
                     rules.Field('title'),
                     rules.Field('comment'),
                     rules.Field('documentation_url'),
                     rules.Field('owner'),
                     rules.Field('shared')]),
        ),
    ]

    def scaffold_form(self):
        form_class = super().scaffold_form()
        form_class.password = PasswordField(
            "Value", description="Leave empty to keep the stored value.")
        return form_class

    def get_query(self):
        """Only the entries the user may see (scope and role)."""
        return visible_secrets(current_user)

    def get_count_query(self):
        """Counted over the same scoped set as the list."""
        return visible_secrets(current_user)

    @expose('/')
    def index_view(self):
        """The list, with the orphaned flags brought up to date first."""
        refresh_orphans()
        return super().index_view()

    def _bind(self, form, model):
        """Apply the host binding of the form, refusing what is out of scope."""
        hostname = (form.hostname.data or '').strip()
        key = (form.key.data or '').strip()
        if not hostname:
            if is_scoped(current_user):
                raise ValidationError("Global entries are outside your scope: "
                                      "bind the entry to one of your hosts.")
            model.host_id = None
            model.hostname = None
            model.orphaned = False
            return
        if not key:
            raise ValidationError("A host-bound entry needs a key.")
        # The form has already written its hostname onto the model, so the
        # current binding is read from the stored host id.
        current = model.get_host()
        if current is None or current.deleted_at is not None \
                or current.hostname != hostname:
            host = Host.objects(hostname=hostname, deleted_at=None).first()
            # Out of scope looks exactly like not existing.
            if host is None or not can_bind(current_user, host):
                raise ValidationError(f"No host {hostname} found.")
            model.bind_to_host(host)
        model.key = key
        model.name = host_secret_name(hostname, key)
        clash = Secret.objects(name=model.name, id__ne=model.id).first()
        if clash:
            raise ValidationError(f"Host {hostname} already has a secret {key}.")

    def on_model_change(self, form, model, is_created):
        if not is_created and not can_access(current_user, model):
            raise ValidationError("Entry not found.")
        if not hasattr(form, 'hostname'):
            # Inline switch in the list: the form carries 'enabled' only.
            return super().on_model_change(form, model, is_created)
        self._bind(form, model)
        if form.password.data:
            model.set_password(form.password.data)
        elif is_created:
            raise ValidationError("A new entry needs a value.")
        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        if not can_access(current_user, model):
            raise ValidationError("Entry not found.")
        return super().on_model_delete(model)

    @expose('/reveal')
    def reveal_view(self):
        """Show the plaintext of one entry, for copying it by hand."""
        entry = self.get_one(request.args.get('id', ''))
        if entry is None or not can_access(current_user, entry):
            abort(404)
        if not can_reveal(current_user, entry):
            flash("Showing values needs the role 'Secret Store: show "
                  "plaintext values'.", 'error')
            return redirect(url_for('.index_view'))
        logger.info("Secret Store: %s revealed entry %s",
                    getattr(current_user, 'email', '?'), entry.name)
        response = make_response(self.render('admin/secret_reveal.html', entry=entry,
                                             value=entry.get_password()))
        response.headers['Cache-Control'] = 'no-store'
        return response

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and can_manage(current_user)

    def get_list_row_actions(self):
        """No 'show value' button for users who may not use it."""
        actions = super().get_list_row_actions()
        if can_reveal_role(current_user):
            return actions
        return [action for action in actions
                if 'reveal_view' not in getattr(action, 'endpoint', '')]
