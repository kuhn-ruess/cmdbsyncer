"""
Host Model View
"""
# pylint: disable=too-few-public-methods
from flask_login import current_user
from flask_admin.actions import action
from flask import flash
from application.views.default import DefaultModelView
from application.models.host import Host

class HostModelView(DefaultModelView):
    """
    Host Model
    """
    column_filters = (
       'hostname',
       'source_account_name',
       'available',
    )

    column_exclude_list = (
        'source_account_id',
        'log'
    )

    column_editable_list = (
        'force_update',
    )

    form_widget_args = {
        'available': {'disabled': True},
        'last_seen': {'disabled': True},
        'source_account_id': {'disabled': True},
        'source_account_name': {'disabled': True},
        'labels': {'disabled': True},
    }

    @action('force_update', 'Force Update')
    def action_update(self, ids):
        """
        Set force Update Attribute
        """
        for host_id in ids:
            host = Host.objects.get(id=host_id)
            host.force_update = True
            host.save()
        flash("Updated {} hosts".format(len(ids)))
        return self.index_view()

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')
