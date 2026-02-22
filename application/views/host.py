"""
Host Model View
"""
from datetime import datetime
# pylint: disable=too-few-public-methods
import re
from flask_login import current_user
from flask import flash, request, redirect, url_for, render_template_string
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter
from flask_admin.model.template import LinkRowAction
from flask_admin.form import rules
from flask_admin.actions import action
from flask_admin.base import expose
from wtforms import HiddenField, Field, StringField, BooleanField
from markupsafe import Markup
from mongoengine.errors import DoesNotExist

from application.plugins.checkmk.models import CheckmkFolderPool #@TODO pre_deletion method for Host so no import needed
from application.plugins.checkmk import get_host_debug_data as cmk_host_debug
from application.plugins.netbox import get_device_debug_data as netbox_host_debug


from application import app
from application.views.default import DefaultModelView
from application.models.host import Host, CmdbField

div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")

# Icon mappings for object types
OBJECT_TYPE_ICONS = {
    'auto': 'fa fa-magic',
    'application': 'fa fa-code',
    'contact': 'fa fa-user',
    'group': 'fa fa-users',
    'host': 'fa fa-server',
    'network': 'fa fa-network-wired',
    'url': 'fa fa-link',
    'custom_1': 'fa fa-cube',
    'custom_2': 'fa fa-cube',
    'custom_3': 'fa fa-cube',
    'custom_4': 'fa fa-cube',
    'custom_5': 'fa fa-cube',
    'custom_6': 'fa fa-cube',
    'undefined': 'fa fa-question-circle',
    'template': 'fa fa-file',
    'cmk_site': 'fa fa-sitemap',
}

def get_debug(hostname, mode):
    """
    Get Output for Host Debug Page
    """

    try:
        Host.objects.get(hostname=hostname)

        output = {}
        output_rules = {}

        #@TODO Restrict by user Rights
        debug_funcs = {
            'checkmk_host': cmk_host_debug,
            'netbox_device': netbox_host_debug,
        }

        attributes, actions, debug_log = debug_funcs[mode](hostname)

        for type_name, data in debug_log.items():
            output_rules[type_name] = data

        if attributes:
            output["Full Attribute List"] = attributes['all']
            if attributes.get('filtered'):
                output["Filtered"] = attributes['filtered']
            output["Outcomes"] =  actions
            additional_attributes = {}
            additional_attributes =  actions.get('custom_attributes', {})

            for additional_attr in actions.get('attributes',[]):
                if attr_value := attributes['all'].get(additional_attr):
                    additional_attributes[additional_attr] = attr_value
            if additional_attributes:
                output["Custom Attributes"] = additional_attributes
        else:
            output["Info: Host disabled by Filter"] = None
        return output, output_rules
    except DoesNotExist:
        return {'Error': "Host not found in Database"}, {}

def _render_object_type_icon(_view, _context, model, _name):
    """
    Render object type with icon
    """
    if not model.object_type:
        return Markup('<span class="text-muted">N/A</span>')
    
    icon_class = OBJECT_TYPE_ICONS.get(model.object_type, 'fa fa-question-circle')
    object_type_display = model.object_type.replace('_', ' ').title()
    
    return Markup(f'<i class="{icon_class}" style="margin-right: 5px;"></i>{object_type_display}')

def _render_datetime(view, context, model, name):
    """
    Render datetime fields in a human-readable format.
    """
    value = getattr(model, name, None)
    if not value:
        return Markup('<span class="text-muted">N/A</span>')
    if isinstance(value, datetime):
        return Markup(value.strftime('%Y-%m-%d %H:%M:%S'))
    return Markup(str(value))

def _render_cmdb_fields(_view, _context, model, _name):
    """
    Render CMD Fields
    """
    if not model.cmdb_fields:
        return Markup("")
    html = '<table class="table table-bordered">'
    for entry in model.cmdb_fields:
        if not entry.field_value:
            continue
        html += f'''
            <tr>
                <th scope="row" style="width: 30%;">
                    {entry.field_name}
                </th>
                <td>
                    <span class="badge badge-info">{entry.field_value}</span>
                </td>
            </tr>
        '''
    html += '</table>'
    return Markup(html)

def _render_labels(_view, _context, model, _name):
    """
    Render Labels
    """
    if not model.labels:
        return Markup("")
    #If the Cache is set, we also show the attributes which we Send to Checkmk
    checkmk_labels = model.cache.get('checkmk_hostattribute', {}).get('attributes', {}).get('all', {})
    html = ""
    for key, value in model.labels.items():
        if not value:
            continue
        if checkmk_labels.get(key) == value:
            del checkmk_labels[key]
        html += f'<span class="badge badge-primary mr-1" style="margin: 2px;">{key}:{value}</span>'

    for key, value in checkmk_labels.items():
        if not value:
            continue
        if model.inventory.get(key) == value:
            continue
        html += f'<span class="badge mr-1" style="margin: 2px; background-color: rgb(43, 181, 120);">{key}:{value}</span>'


    return Markup(html)

def _render_cmdb_template(_view, _context, model, _name):
    """
    Render CMD Template
    """
    if not model.cmdb_template:
        return Markup("")
    html = '<table class="table table-bordered">'
    for key, value in model.cmdb_template.labels.items():
        html += f'''
            <tr>
                <th scope="row" style="width: 30%;">
                    {key}
                </th>
                <td>
                    <span class="badge badge-info">{value}</span>
                </td>
            </tr>
        '''
    html += '</table>'
    return Markup(html)

class StaticLabelWidget:
    """
    Design for Lablels in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        entries = []
        for key, value in field.data.items():
            html_entry = ""
            html_entry += f'<span class="badge badge-primary">{key}</span>:'
            html_entry += f'<span class="badge badge-info">{value}</span>'
            entries.append(html_entry)
        html += ", ".join(entries)
        html += "</div></div>"
        return Markup(html)

class StaticLabelField(Field):
    """
    Helper for Widget
    """
    widget = StaticLabelWidget()

    def _value(self):
        return str(self.data) if self.data else ''

class StaticTemplateLabelWidget:
    """
    Design for Template Labels in Views
    """
    def __call__(self, field, **kwargs):
        model = field.object_data
        if not model or not hasattr(model, 'cmdb_template') or not model.cmdb_template:
            return Markup('<div class="alert alert-info">No Template selected</div>')

        template = model.cmdb_template

        if not hasattr(template, 'labels') or not template.labels:
            return Markup('<div class="alert alert-warning">No Labels in Template</div>')

        html = '<div class="card"><div class="card-body">'
        entries = []
        for key, value in template.labels.items():
            html_entry = ""
            html_entry += f'<span class="badge badge-primary">{key}</span>:'
            html_entry += f'<span class="badge badge-info">{value}</span>'
            entries.append(html_entry)
        html += ", ".join(entries)
        html += '</div></div>'
        return Markup(html)

class StaticTemplateLabelField(Field):
    """
    Helper for Widget
    """
    widget = StaticTemplateLabelWidget()

    def _value(self):
        return str(self.data) if self.data else ''

class StaticLogWidget:
    """
    Design for Lists in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        html += "<table class='table'>"
        for line in field.data:
            html += f"<tr><td>{line[:160]}</td></tr>"
        html += "</table>"
        html += "</div></div>"
        return Markup(html)

class StaticLogField(Field):
    """
    Helper for Widget
    """
    widget = StaticLogWidget()

    def _value(self):
        return str(self.data) if self.data else ''

def get_rule_json(_view, _context, model, _name):
    """
    Export Given Rulesets
    """
    return model.to_json()

class FilterAccountRegex(BaseMongoEngineFilter):
    """
    Filter Value with Regex
    """

    def apply(self, query, value):
        return query.filter(source_account_name__icontains=value)

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

class FilterObjectType(BaseMongoEngineFilter):
    """
    Filter Value
    """

    def apply(self, query, value):
        return query.filter(object_type__icontains=value)

    def operation(self):
        return "contains"

class FilterPoolFolder(BaseMongoEngineFilter):
    """
    Filter Value
    """

    def apply(self, query, value):
        return query.filter(folder__iexact=value)

    def operation(self):
        return "contains"

class FilterLabelKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Label
    """

    def apply(self, query, value):
        key, value = value.split(':', 1)

        # Filter for None values, but only if key exists
        if value.strip().lower() == 'none':
            pipeline = {
                "$and": [
                    {f"labels.{key}": None},
                    {f"labels.{key}": {"$exists": True}}
                ]
            }
            return query.filter(__raw__=pipeline)

        org_value = False

        try:
            org_value = int(value)
        except ValueError:
            pass

        if value == '*':
            value = '.*'


        if org_value:
            pipeline = {
                    "$or": [
                    {f'labels.{key}': {"$regex":  value, "$options": "i"}},
                    {f'labels.{key}': org_value}
                ]
            }

        else:
            pipeline = {
                    f'labels.{key}': {"$regex":  value, "$options": "i"},
            }
        try:
            return query.filter(__raw__=pipeline)
        except Exception as error:
            flash('danger', error)
        return False

    def operation(self):
        return "regex search"

class FilterInventoryKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Inventory
    """

    def apply(self, query, value):
        key, value = value.split(':', 1)

        # Filter for None values, but only if key exists
        if value.strip().lower() == 'none':
            pipeline = {
                "$and": [
                    {f"inventory.{key}": None},
                    {f"inventory.{key}": {"$exists": True}}
                ]
            }
            return query.filter(__raw__=pipeline)

        org_value = False

        try:
            org_value = int(value)
        except ValueError:
            pass

        if value == '*':
            value = '.*'

        if org_value:
            pipeline = {
                    "$or": [
                    {f'inventory.{key}': {"$regex":  value, "$options": "i"}},
                    {f'inventory.{key}': org_value}
                ]
            }
        else:
            pipeline = {
                    f'inventory.{key}': {"$regex":  value, "$options": "i"},
            }
        try:
            return query.filter(__raw__=pipeline)
        except Exception as error:
            flash('danger', error)
        return False

    def operation(self):
        return "regex search"

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

    can_create = True
    can_edit = True
    can_export = True
    can_view_details = True

    column_details_list = [
        'hostname', 'inventory', 'labels', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
        'cmdb_template',
        'sync_id',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
    ]

    column_export_list = ('hostname', )

    column_filters = (
       FilterHostnameRegex(
        Host,
        "Hostname",
       ),
       FilterObjectType(
        Host,
        "Object Type",
       ),
    )

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_fields': _render_cmdb_fields,
        'object_type': _render_object_type_icon,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'hostname': "Object Name",
        'source_account_name': "Account",
        'cmdb_fields': "CMDB Attributes",
    }

    export_types = ['syncer_rules',]

    form_overrides = {
        'inventory': StaticLabelField,
        'log': StaticLogField,
    }

    form_rules = [
        rules.Field('hostname'),
        rules.FieldSet(('cmdb_fields',), "CMDB Fields"),
        rules.FieldSet(('inventory', 'log'), "Data"),
    ]

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {'style': 'background-color: #2EFE9A;', 'size': 10},
                        'field_value': {'style': 'background-color: #81DAF5;', 'size': 40},
                    },
                    'form_rules' : [
                        div_open,
                        rules.NestedRule(
                            ('field_name', 'field_value')
                        ),
                        div_close,
                    ]
                }
            }
        }
    }

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status

        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('CMDB Attributes')
            self.column_exclude_list.append('cmdb_fields')

        super().__init__(model, **kwargs)

    def get_export_name(self, export_type):
        """
        Generates a filename for exporting data based on the model name and current timestamp.

        Args:
            export_type: The type of export being performed (currently unused).

        Returns:
            str: A string representing the export filename in the format
                 '<ModelName>_<YYYYMMDDHHMM>.syncer_json'.
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True)

    def on_model_change(self, form, model, is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.is_object = True
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        # Set Extra Fields
        new_labels = {x['field_name']: x['field_value'] for x in form.cmdb_fields.data}
        model.object_type = 'template'

        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('objects')


class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_create = True
    can_edit = True
    can_export = True
    can_set_page_size = True
    can_view_details = True

    page_size = app.config['HOST_PAGESIZE']

    column_details_list = [
        'hostname', 'folder', 'available','labels', 'inventory', 'cmdb_template', 'log',
        'last_import_seen', 'last_import_sync', 'last_import_id',
        'source_account_name', 'raw', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
        'sync_id',
        'cmdb_fields',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
        'last_import_id',
        'last_import_sync',
    ]


    column_export_list = ('hostname', )

    column_extra_row_actions = [
        LinkRowAction("fa fa-rocket", app.config['BASE_PREFIX'] + \
                    "admin/host/debug?obj_id={row_id}"),
    ]

    column_filters = (
       FilterHostnameRegex(
        Host,
        "Hostname",
       ),
       FilterAccountRegex(
           Host,
           'Account',
       ),
       FilterLabelKeyAndValue(
        Host,
        "Label Key:Value"
       ),
       FilterInventoryKeyAndValue(
        Host,
        "Inventory Key:Value"
       ),
       FilterPoolFolder(
           Host,
           'CMK Pool Folder'
       ),
    )

    column_formatters = {
        'log': format_log,
        'labels': _render_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_template': _render_cmdb_template,
        'last_import_seen': _render_datetime,
        'object_type': _render_object_type_icon,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
        #'cmdb_fields': "CMDB Attributes",
        'cmdb_template': "From Template",
        'labels_from_template': "Labels from Template",
    }

    column_sortable_list = ('hostname',
                            'last_import_seen', 
                            'last_import_sync')

    export_types = ['syncer_rules',]

    form_overrides = {
        'hostname': StringField,
        'last_import_seen': HiddenField,
        'last_import_sync': HiddenField,
        'last_import_id': HiddenField,
        'raw': HiddenField,
        'folder': HiddenField,
        'sync_id': HiddenField,
        'cache': HiddenField,
        'source_account_name': HiddenField,
        'source_account_id': HiddenField,
        'inventory': StaticLabelField,
        'log': StaticLogField,
        'labels': HiddenField,

    }

    form_rules = [
        rules.FieldSet((
            rules.Field('hostname'),
            rules.NestedRule(('object_type', 'available', 'cmdb_template', 'labels_from_template')),
            ), "CMDB Options"),
        rules.FieldSet(('cmdb_fields',), "CMDB Fields"),
        rules.FieldSet(('inventory', 'log'), "Data"),
    ]

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {
                            'style': (
                                'background-color: #2EFE9A; '
                                'border-radius: 5px; '
                                'padding: 6px 10px;'
                                'margin-right: 10px; '
                                'font-weight: bold; '
                                'border: 1px solid #1abc9c;'
                            ),
                            'size': 15
                        },
                        'field_value': {
                            'style': (
                                'background-color: #81DAF5; '
                                'border-radius: 5px; '
                                'padding: 6px 10px; '
                                'font-family: monospace; '
                                'margin-left: 10px; '
                                'border: 1px solid #3498db;'
                            ),
                            'size': 40
                        },
                    },
                    'form_rules': [
                        rules.HTML('<div class="form-row align-items-center" style="margin-bottom: 8px;">'),
                        rules.NestedRule(('field_name', 'field_value')),
                        rules.HTML('</div>'),
                    ]
                }
            }
        }
    }

    @expose('/debug')
    def debug(self):
        """
        Checkmk specific Debug Page
        """
        if obj_id := request.args.get('obj_id'):
            hostname = Host.objects.get(id=obj_id).hostname
        else:
            hostname = request.args.get('hostname','').strip()
        mode = request.args.get('mode', 'checkmk_host')



        output= {}
        output_rules = {}

        if hostname:
            output, output_rules = get_debug(hostname, mode)

        base_urls = {
            #'filter': f"{app.config['BASE_PREFIX']}admin/checkmkfilterrule/edit/?id=",
            #'rewrite': f"{app.config['BASE_PREFIX']}admin/checkmkrewriteattributerule/edit/?id=",
            #'actions': f"{app.config['BASE_PREFIX']}admin/checkmkrule/edit/?id=",
            'CustomAttributes': f"{app.config['BASE_PREFIX']}admin/customattributerule/edit/?id=",
        }
        new_rules = {}
        for rule_group, rule_data in output_rules.items():
            new_rules.setdefault(rule_group, [])
            for rule in rule_data:
                #if rule_group in base_urls:
                if rule_group in base_urls:
                    rule['rule_url'] = f"{base_urls[rule_group]}{rule['id']}"
                else:
                    rule['rule_url'] = '#'
                new_rules[rule_group].append(rule)

        if "Error" in output:
            output = f"Error: {output['Error']}"

        return self.render('debug_host.html', hostname=hostname, output=output,
                           rules=new_rules, mode=mode)


    def __init__(self, model, **kwargs):
        """
        Overwrite based on status
        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('cmdb_fields')
            self.column_exclude_list.append('cmdb_template')

        if app.config['LABEL_PREVIEW_DISABLED']:
            self.column_exclude_list.append('labels')

        super().__init__(model, **kwargs)

    def get_export_name(self, _export_type):
        """
        Generates a filename for exporting data based on the model name and current timestamp.

        Args:
            export_type: The type of export being performed (currently unused).

        Returns:
            str: A string representing the export filename in the format
                 '<ModelName>_<YYYYMMDDHHMM>.syncer_json'.
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object__ne=True)


    def scaffold_form(self):
        form_class = super().scaffold_form()
        form_class.labels_from_template = StaticTemplateLabelField()
        return form_class

    def edit_form(self, obj=None):
        form = super().edit_form(obj)
        if obj and hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj

        # Sort cmdb_fields alphabetically and set correct field types
        cmdb_entries = getattr(getattr(form, 'cmdb_fields', None), 'entries', None)
        if not cmdb_entries:
            return form

        # Sort entries alphabetically by field_name
        cmdb_entries.sort(
            key=lambda x: str(getattr(x, 'field_name', None).data).lower()
        )

        return form

    def get_form_field_type(self, field_name):
        """
        Dynamically determine the WTForms field type for a given field_name
        based on your configuration (e.g., app.config['CMDB_MODELS']).
        Returns a WTForms Field class.
        """
        field_type = app.config['CMDB_MODELS']['all'].get(field_name, {'type': 'string'})
        field_type = field_type['type']
        if field_type == 'boolean':
            return BooleanField
        return StringField

    def create_form(self, obj=None):
        form = super().create_form(obj)
        if hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj
        return form

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('host')

    def on_model_delete(self, model):
        """
        Housekeeping on host deletion
        """
        if model.folder:
            folder = CheckmkFolderPool.objects.get(folder_name__iexact=model.folder)
            if folder.folder_seats_taken > 0:
                folder.folder_seats_taken -= 1
                folder.save()


    def on_model_change(self, form, model, is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
        # Set Extra Fields
        cmdb_fields = app.config['CMDB_MODELS'].get(form.object_type.data, {})
        cmdb_fields.update(app.config['CMDB_MODELS']['all'])
        new_labels = {x['field_name']: x['field_value'] for x in form.cmdb_fields.data}

        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

        for key in cmdb_fields:
            if key not in new_labels:
                new_field = CmdbField()
                new_field.field_name = key
                model.cmdb_fields.append(new_field)
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('cmdb_fields')
            self.column_exclude_list.append('cmdb_template')

        # Bugfix, ohne we loose the availibilty to edit after save
        self.can_edit = True

    @action('set_template', 'Set Template', 
            'Are you sure you want to update the selected hosts?')
    def action_set_template(self, ids):
        """
        Action to set CMDB template
        """
        url = url_for('.set_template_form', ids=','.join(ids))
        return redirect(url)


    @expose('/set_template_form')
    def set_template_form(self):
        """
        Custom form for template selection
        """
        ids = request.args.get('ids', '').split(',')
        templates = self.get_template_list()

        template_html = """
        <div class="container mt-4">
            <h3>Set CMDB Template</h3>
            <form method="POST" action="{{ url_for('.process_template_assignment') }}">
                <input type="hidden" name="host_ids" value="{{ ids|join(',') }}">
                
                <div class="form-group">
                    <label for="template_id">Select Template:</label>
                    <select class="form-control" id="template_id" name="template_id" required>
                        <option value="">Choose a template...</option>
                        {% for template in templates %}
                        <option value="{{ template.id }}">{{ template.hostname }}</option>
                        {% endfor %}
                    </select>
                </div>
                
                <div class="form-group">
                    <button type="submit" class="btn btn-primary">Apply Template</button>
                    <a href="{{ url_for('.index_view') }}" class="btn btn-secondary">Cancel</a>
                </div>
            </form>
        </div>
        """
        return render_template_string(template_html, ids=ids, templates=templates)

    @expose('/process_template_assignment', methods=['POST'])
    def process_template_assignment(self):
        """
        Process the template assignment
        """
        host_ids = request.form.get('host_ids', '').split(',')
        template_id = request.form.get('template_id')

        if not template_id:
            flash('Please select a template', 'error')
            return redirect(url_for('.index_view'))

        try:
            # Get the template
            template = Host.objects(id=template_id).first()
            if not template:
                flash('Template not found', 'error')
                return redirect(url_for('.index_view'))

            # Apply template to selected hosts
            updated_count = 0
            for host_id in host_ids:
                if not host_id.strip():
                    continue

                host = Host.objects(id=host_id).first()
                if host:
                    host.cmdb_template = template
                    
                    # Apply the same logic as on_model_change
                    host.last_import_sync = datetime.now()
                    host.last_import_seen = datetime.now()
                    host.cache = {}
                    host.source_account_name = "cmdb"
                    
                    # Set Extra Fields from CMDB config
                    cmdb_fields = app.config['CMDB_MODELS'].get(host.object_type, {})
                    cmdb_fields.update(app.config['CMDB_MODELS']['all'])
                    
                    # Create labels from existing cmdb_fields
                    new_labels = {x.field_name: x.field_value for x in host.cmdb_fields if x.field_value}
                    
                    host.update_host(new_labels)
                    host.set_inventory_attributes('cmdb')

                    # Add missing CMDB fields based on configuration
                    existing_field_names = {x.field_name for x in host.cmdb_fields}
                    for key in cmdb_fields:
                        if key not in existing_field_names:
                            new_field = CmdbField()
                            new_field.field_name = key
                            host.cmdb_fields.append(new_field)

                    host.save()
                    updated_count += 1

            flash(f'Template applied to {updated_count} hosts', 'success')

        except Exception as e:
            flash(f'Error applying template: {str(e)}', 'error')

        return redirect(url_for('.index_view'))

    def get_template_list(self):
        """Get available CMDB templates for the action form"""
        try:
            templates = Host.objects(is_object=True, object_type='template')
            return list(templates)
        except Exception:
            return []
