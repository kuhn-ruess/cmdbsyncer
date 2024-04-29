"""
Host Model View
"""
# pylint: disable=too-few-public-methods
import re
from mongoengine.errors import DoesNotExist
from flask_login import current_user
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter

from markupsafe import Markup

from application import app
from application.views.default import DefaultModelView
from application.models.host import Host
from application.models.config import Config


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
        return query.filter(__raw__={f'labels.{value}': {'$exists': True}})

    def operation(self):
        return "exists"

def format_log(v, c, m, p):
    """ Format Log view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<ul>"
    for entry in m.log:
        html+=f"<li>{entry}</li>"
    html += "</ul>"
    return Markup(html)

def format_cache(v, c, m, p):
    """ Format cache"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for key, value in m.cache.items():
        html += f"<tr><th>{key}</th><td>"
        html += "<table>"
        for sub_key, sub_value in value.items():
            html += f"<tr><td>{sub_key}</td><td>{sub_value}</td></tr>"
        html += "</table>"
        html += "</td></tr>"
    html += "</table>"
    return Markup(html)

def format_labels(v, c, m, p):
    """ Format Labels view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for key, value in m.labels.items():
        html += f"<tr><th>{key}</th><td>{value}</td></tr>"
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
    # BUG with MongoDB and Forks
    columns = [
        'hostname',
    ]

    # BUG with MongoDB and Forks
    #try:
    #    config = Config.objects.get()
    #except DoesNotExist:
    #    pass
    #else:
    #    columns += config.export_labels_list
    #    columns += config.export_inventory_list

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
    # BUG with MongoDB and Forks
    return {}
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



class ObjectModelView(DefaultModelView):
    """
    Onlye show objects
    """

    can_edit = False
    can_create = False
    can_view_details = True

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True)


    column_labels = {
        'hostname': "Object Name",
        'source_account_name': "Account"
    }

    column_exclude_list = (
        'source_account_id',
        'sync_id',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
        'last_export',
        'force_update',
    )

    column_details_list = [
        'hostname', 'inventory', 'labels', 'cache'
    ]

    column_formatters = {
        'labels': format_labels,
        'inventory': format_inventory,
    }


class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_edit = False
    can_create = False
    can_view_details = True
    can_export = True

    export_types = ['xlsx', 'csv']


    column_sortable_list = ('hostname',
                            'last_import_seen', 
                            'last_import_sync')


    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object__ne=True)

    column_details_list = [
        'hostname', 'folder', 'available', 'force_update', 'labels', 'inventory', 'log',
        'last_import_seen', 'last_import_sync', 'last_export', "export_problem",
        'source_account_name', 'raw', 'cache'
    ]
    column_sortable_list = ('hostname',
                            'last_import_seen', 
                            'last_import_sync')

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
    )

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
    }

    page_size = 25
    can_set_page_size = True

    column_export_list = get_export_colums()
    column_formatters_export = get_export_values()

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
    }

    column_exclude_list = (
        'source_account_id',
        'sync_id',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
        'last_export',
        'force_update',
    )

    column_editable_list = (
        'force_update',
    )

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status

        """

        if app.config['DEBUG'] == True:
            self.can_edit = True

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')
