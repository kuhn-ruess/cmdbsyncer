"""
Default Model Views
"""
from copy import deepcopy
from flask import url_for, redirect, flash, request
from flask_login import current_user
from flask_admin import AdminIndexView
from flask_admin import expose
from flask_admin.contrib.mongoengine import ModelView
from flask_admin.model.template import EndpointLinkRowAction
from flask_admin.helpers import get_redirect_target
from flask_admin.model.helpers import get_mdict_item_or_list

from mongoengine.errors import NotUniqueError

class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """
    page_size = 300
    column_extra_row_actions = [
        EndpointLinkRowAction("fa fa-clone", ".clone_view"),
    ]

    @expose("/clone", methods=("GET",))
    def clone_view(self):
        """
        Clone given model
        """

        entry_id = get_mdict_item_or_list(request.args, 'id')

        # Duplicate current record
        return_url = get_redirect_target() or self.get_url('.index_view')

        if not self.can_create:
            return redirect(return_url)

        old_model = self.get_one(entry_id)
        if old_model is None:
            flash('Entry does not exist.', 'error')
            return redirect(return_url)

        obj = deepcopy(old_model)
        obj.id = None
        if hasattr(obj, 'name'):
            obj.name += " (Clone)"
        try:
            obj.save()
        except NotUniqueError:
            flash('Entry with Name already exist', 'error')
            return redirect(return_url)

        flash("Entry Cloned", 'success')
        return redirect(return_url)


    def on_model_change(self, form, model, is_created):
        """
        Cleanup Fields
        """

        for attr in [x for x in dir(model) if not x.startswith('_')]:
            current = getattr(model, attr)
            if isinstance(current, str):
                setattr(model, attr, current.strip())

        try:
            return super().on_model_change(form, model, is_created)
        except NotUniqueError as exce:
            flash("Duplicate Entry Name", "error")
            raise ValueError("NotUniqueError: Object name not Unique") from exce


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))

class IndexView(AdminIndexView):
    """
    Index View Overwrite for auth
    """
    def is_visible(self):
        return False

    def is_accessible(self):
        return current_user.is_authenticated \
                and not current_user.force_password_change

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))
