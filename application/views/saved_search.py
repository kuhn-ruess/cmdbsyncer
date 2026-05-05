"""
Saved Search admin view + helper endpoints.

Two surfaces:
  * `SavedSearchView` — a flask-admin ModelView under "Settings" that
    lets the owner browse / delete / toggle shared on their presets.
  * `register_saved_search_routes(host_view)` — wires `/save` and
    `/delete_preset/<id>` POST routes onto an existing list view (here
    HostModelView) so the inline "Save current filter" button can call
    them without leaving the host list page.
"""
from flask import flash, redirect, request, url_for
from flask_admin.base import expose
from flask_admin.contrib.mongoengine import ModelView
from flask_login import current_user
from mongoengine.errors import DoesNotExist
from mongoengine.queryset.visitor import Q

from application.models.saved_search import SavedSearch


class SavedSearchView(ModelView):  # pylint: disable=too-many-public-methods,too-many-ancestors
    """
    Manage saved filter presets. The list view shows everything the
    current user is allowed to see (own + shared), but only the owner
    of a row can edit or delete it.
    """
    can_create = False  # presets are always created from a list page
    can_edit = True
    can_delete = True
    column_list = ('name', 'path', 'shared', 'owner_email', 'created_at')
    column_filters = ('path', 'shared', 'owner_email')
    column_default_sort = ('-created_at',)
    form_excluded_columns = ('owner_email', 'created_at', 'path', 'query_string')

    def is_accessible(self):
        return current_user.is_authenticated

    def get_query(self):
        if not current_user.is_authenticated:
            return SavedSearch.objects.none()
        if current_user.global_admin:
            return SavedSearch.objects()
        return SavedSearch.objects(
            Q(owner_email=current_user.email) | Q(shared=True)
        )

    def on_model_change(self, form, model, is_created):
        # Editing: keep ownership intact even if a future form change
        # exposed the field.
        super().on_model_change(form, model, is_created)
        if not model.owner_email:
            model.owner_email = current_user.email

    def on_model_delete(self, model):
        if not current_user.global_admin and \
                model.owner_email != getattr(current_user, 'email', None):
            raise PermissionError(
                "Only the owner can delete this saved search."
            )


def list_for_path(path):
    """
    Return the saved searches the current user is allowed to see for a
    given list path. Owner's first, shared second, alphabetical inside
    each group.
    """
    if not current_user.is_authenticated:
        return []
    own = list(SavedSearch.objects(
        path=path, owner_email=current_user.email
    ).order_by('name'))
    shared = list(SavedSearch.objects(
        path=path, shared=True, owner_email__ne=current_user.email
    ).order_by('name'))
    return own + shared


def register_saved_search_routes(host_view_cls):
    """
    Attach two endpoints to a flask-admin list view so the "Save current
    filter" / "Delete preset" buttons can post back without their own
    blueprint. Decorators are applied here at import time.
    """

    @expose('/save_preset', methods=['POST'])
    def save_preset(self):  # pylint: disable=unused-argument
        if not current_user.is_authenticated:
            return redirect(url_for('admin.login_view'))
        name = (request.form.get('name') or '').strip()
        querystring = request.form.get('query_string') or ''
        path = request.form.get('path') or request.path
        shared = request.form.get('shared') == 'on'
        if not name:
            flash('Saved Search name is required', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        SavedSearch(
            name=name[:120],
            path=path[:255],
            query_string=querystring,
            owner_email=current_user.email,
            shared=shared,
        ).save()
        flash(f'Saved current filter as "{name}"', 'success')
        return redirect(request.referrer or url_for('.index_view'))

    @expose('/delete_preset/<preset_id>', methods=['POST'])
    def delete_preset(self, preset_id):  # pylint: disable=unused-argument
        if not current_user.is_authenticated:
            return redirect(url_for('admin.login_view'))
        try:
            preset = SavedSearch.objects.get(id=preset_id)
        except DoesNotExist:
            flash('Saved Search not found', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        if not current_user.global_admin and \
                preset.owner_email != current_user.email:
            flash('Only the owner can delete this preset', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        preset.delete()
        flash(f'Deleted preset "{preset.name}"', 'success')
        return redirect(request.referrer or url_for('.index_view'))

    host_view_cls.save_preset = save_preset
    host_view_cls.delete_preset = delete_preset
    return host_view_cls
