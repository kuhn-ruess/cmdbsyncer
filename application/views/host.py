"""
Host Model View
"""
from datetime import datetime
# pylint: disable=too-few-public-methods
import re
from flask_login import current_user
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter
from flask_admin.model.template import LinkRowAction

from mongoengine.queryset.visitor import Q
from markupsafe import Markup


from application import app
from application.views.default import DefaultModelView
from application.models.host import Host

def get_rule_json(_view, _context, model, _name):
    """
    Export Given Rulesets
    """
    return model.to_json()


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

class FilterInventoryKey(BaseMongoEngineFilter):
    """
    Filter for Inventory Key
    """

    def apply(self, query, value):
        return query.filter(__raw__={f'inventory.{value}': {'$exists': True}})

    def operation(self):
        return "exists"


class FilterLabelKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Label
    """

    def apply(self, query, value):
        key, value = value.split(':')
        pipeline_org = {
                f'labels__{key}': value,
        }
        try:
            pipeline_int = {
                    f'labels__{key}': int(value),
            }
        except ValueError:
            pipeline_int = False

        if pipeline_int:
            return query.filter(Q(**pipeline_org) | Q(**pipeline_int))
        return query.filter(**pipeline_org)
        

    def operation(self):
        return "search"

class FilterInventoryKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Inventory
    """

    def apply(self, query, value):
        key, value = value.split(':')
        pipeline_org = {
                f'inventory__{key}': value,
        }
        try:
            pipeline_int = {
                    f'inventory__{key}': int(value),
            }
        except ValueError:
            pipeline_int = False

        if pipeline_int:
            return query.filter(Q(**pipeline_org) | Q(**pipeline_int))
        return query.filter(**pipeline_org)

    def operation(self):
        return "search"

def format_log(v, c, m, p):
    """ Format Log view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<ul>"
    for entry in m.log:
        html+=f"<li>{entry[:200]}</li>"
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
        labels.append(f"{entry.key}:{entry.value}")
    return Markup(", ".join(labels))

def format_inventory_export(v, c, m, p):
    """ Format Inventory view"""
    # pylint: disable=invalid-name, unused-argument
    inventory = []
    for key, value in m.inventory.items():
        inventory.append(f"{key}:{value}")
    return Markup(", ".join(inventory))



class ObjectModelView(DefaultModelView):
    """
    Onlye show objects
    """

    can_edit = False
    can_create = False
    can_view_details = True

    column_filters = (
       'hostname',
       'object_type',
    )

    can_export = True

    export_types = ['syncer_rules',]

    column_export_list = ('hostname', )

    column_formatters_export = {
        'hostname': get_rule_json
    }


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
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
    }

    def get_export_name(self, _export_type):
        """
        Overwrite Filename
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status

        """

        if app.config['DEBUG'] is True:
            self.can_edit = True

        super().__init__(model, **kwargs)


class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_edit = False
    can_create = False
    can_view_details = True
    can_export = True

    export_types = ['syncer_rules',]

    column_export_list = ('hostname', )

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_extra_row_actions = [
        LinkRowAction("fa fa-rocket", app.config['BASE_PREFIX'] + \
                    "admin/checkmkrule/debug?obj_id={row_id}"),
    ]


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
       FilterLabelKeyAndValue(
        Host,
        "Label Key:Value"
       ),
       FilterInventoryKey(
        Host,
        "Inventory Key"
       ),
       FilterInventoryKeyAndValue(
        Host,
        "Inventory Key:Value"
       ),
    )

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
    }

    page_size = 25
    can_set_page_size = True


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

    def get_export_name(self, _export_type):
        """
        Overwrite Filename
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status

        """

        if app.config['DEBUG'] is True:
            self.can_edit = True

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')
