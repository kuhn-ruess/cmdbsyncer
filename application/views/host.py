"""
Host Model View
"""
# pylint: disable=too-few-public-methods
import re
from mongoengine.errors import DoesNotExist
from flask_login import current_user
from flask_admin.actions import action
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter

from flask import flash
from flask import Markup

from application.views.default import DefaultModelView
from application.models.host import Host
from application.models.config import Config


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

def format_labels_export(v, c, m, p):
    """ Format Labels view"""
    # pylint: disable=invalid-name, unused-argument
    labels = []
    for entry in m.labels:
        print(entry.key, flush=True)
        labels.append(f"{entry.key}:{entry.value}")
    return Markup(", ".join(labels))

def format_inventory_export(v, c, m, p):
    """ Format Inventory view"""
    # pylint: disable=invalid-name, unused-argument
    inventory = []
    for key, value in m.inventory.items():
        inventory.append(f"{key}:{value}")
    return Markup(", ".join(inventory))


def get_export_colums():
    """
    Return list of columns to export
    """
    columns = [
        'hostname',
    ]

    try:
        config = Config.objects.get()
    except DoesNotExist:
        pass
    else:
        columns += config.export_labels_list
        columns += config.export_inventory_list

    columns += [
        'sync_id',
        'source_account_name',
        'available',
    ]
    return columns

def get_export_values():
    """
    Dynamic fill needed fields
    """
    try:
        config = Config.objects.get()
    except DoesNotExist:
        return {}

    functions = {}

    for field in config.export_inventory_list:
        functions[field] = lambda v, c, m, p: m.inventory.get(p)
    for field in config.export_labels_list:
        functions[field] = lambda v, c, m, p: m.get_labels().get(p)
    return functions




class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_edit = False
    can_view_details = True
    can_export = True

    export_types = ['xlsx', 'csv']


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

    column_export_list = get_export_colums()
    column_formatters_export = get_export_values()

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
    }

    column_exclude_list = (
        'source_account_id',
        'sync_id',
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
        flash(f"Updated {len(ids)} hosts")
        return self.index_view()

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')
