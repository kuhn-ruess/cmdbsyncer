"""
Host Model View
"""
# pylint: disable=too-few-public-methods
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
       'account_name',
       'available_on_source',
    )

    column_exclude_list = (
        'available_on_target',
        'last_update_on_target',
        'account_id',
        'log'
    )

    column_editable_list = (
        'force_update_on_target',
        'disable_on_target',
    )

    form_widget_args = {
        'available_on_source': {'disabled': True},
        'last_seen_on_source': {'disabled': True},
        'available_on_target': {'disabled': True},
        'last_update_on_target': {'disabled': True},
        'disable_on_target': {'disabled': True},
        'account_id': {'disabled': True},
        'account_name': {'disabled': True},
        'labels': {'disabled': True},
    }

    @action('force_update', 'Force Update')
    def action_update(self, ids):
        """
        Set force Update Attribute
        """
        for host_id in ids:
            host = Host.objects.get(id=host_id)
            host.force_update_on_target = True
            host.save()
        flash("Updated {} hosts".format(len(ids)))
        return self.index_view()
