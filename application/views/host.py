"""
Host Model View
"""
# pylint: disable=too-few-public-methods
import re
from flask_login import current_user
from flask_admin.model.template import LinkRowAction
from flask_admin.actions import action
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter

from flask import flash
from flask import Markup

from application.views.default import DefaultModelView
from application.models.host import Host


class FilterLabelValue(BaseMongoEngineFilter):
    """
    Filter for Label Value
    """

    def apply(self, query, value):
        return query.filter(labels__value__icontains=value)

    def operation(self):
        return "contains"

class FilterHostnameRegex(BaseMongoEngineFilter):
    """
    Filter Value with Regex
    """

    def apply(self, query, value):
        regex = re.compile(value)
        return query.filter(hostname=regex)

    def operation(self):
        return "regex"

class FilterLabelKey(BaseMongoEngineFilter):
    """
    Filter for Label Key
    """

    def apply(self, query, value):
        return query.filter(labels__key__icontains=value)

    def operation(self):
        return "contains"

def format_log(v, c, m, p):
    """ Format Log view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<ul>"
    for entry in m.log:
        html+=f"<li>{entry}</li>"
    html += "</ul>"
    return Markup(html)

def format_labels(v, c, m, p):
    """ Format Labels view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for entry in m.labels:
        html += f"<tr><th>{entry.key}</th><td>{entry.value}</td></tr>"
    html += "</table>"
    return Markup(html)

def format_inventory(v, c, m, p):
    """ Format Inventory view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for key, value in m.inventory.items():
        html += f"<tr><th>{key}</th><td>{value}</td></tr>"
    html += "</table>"
    return Markup(html)

class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_edit = False
    can_view_details = True


    column_details_list = [
        'hostname', 'folder', 'available', 'force_update', 'labels', 'inventory', 'log',
        'last_import_seen', 'last_import_sync', 'last_export', "export_problem",
        'source_account_name',
    ]
    column_filters = (
       'hostname',
       FilterHostnameRegex(
        Host,
        "Hostname Regex",
       ),
       'source_account_name',
       'available',
       FilterLabelKey(
        Host,
        "Label Key"
       ),
       FilterLabelValue(
        Host,
        "Label Value"
       ),
    )

    page_size = 25
    can_set_page_size = True




    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
    }

    column_exclude_list = (
        'source_account_id',
        'inventory',
        'log',
        'folder',
    )

    column_editable_list = (
        'force_update',
    )

    #column_extra_row_actions = [LinkRowAction('fa fa-heartbeat', '/debug_rules?hostid={row_id}')]


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
        #pylint: disable=no-self-use
        return current_user.is_authenticated and current_user.has_right('host')
