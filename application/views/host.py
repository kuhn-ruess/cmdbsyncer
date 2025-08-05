"""
Host Model View
"""
from datetime import datetime
# pylint: disable=too-few-public-methods
import re
from flask_login import current_user
from flask import flash
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter
from flask_admin.model.template import LinkRowAction
from flask_admin.form import rules
from wtforms import HiddenField, Field, StringField, BooleanField
from markupsafe import Markup


from application import app
from application.views.default import DefaultModelView
from application.models.host import Host, CmdbField

div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")

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


class FilterHostnameRegex(BaseMongoEngineFilter):
    """
    Filter Value with Regex
    """

    def apply(self, query, value):
        regex = re.compile(value)
        return query.filter(hostname=regex)

    def operation(self):
        return "regex"


class FilterLabelKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Label
    """

    def apply(self, query, value):
        key, value = value.split(':', 1)

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
       'hostname',
       'object_type',
    )

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_fields': _render_cmdb_fields,
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


class HostModelView(DefaultModelView):
    """
    Host Model
    """
    can_create = True
    can_edit = True
    can_export = True
    can_set_page_size = True
    can_view_details = True

    column_details_list = [
        'hostname', 'folder', 'available','labels', 'inventory', 'cmdb_template', 'log',
        'last_import_seen', 'last_import_sync', 'last_import_id',
        'source_account_name', 'raw', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
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

    column_extra_row_actions = [
        LinkRowAction("fa fa-rocket", app.config['BASE_PREFIX'] + \
                    "admin/checkmkrule/debug?obj_id={row_id}"),
    ]

    column_filters = (
       FilterHostnameRegex(
        Host,
        "Hostname",
       ),
       'source_account_name',
       'available',
       FilterLabelKeyAndValue(
        Host,
        "Label Key:Value"
       ),
       FilterInventoryKeyAndValue(
        Host,
        "Inventory Key:Value"
       ),
    )

    column_formatters = {
        'log': format_log,
        'labels': format_labels,
        'inventory': format_inventory,
        'cache': format_cache,
        'cmdb_fields': _render_cmdb_fields,
        'cmdb_template': _render_cmdb_template,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
        'cmdb_fields': "CMDB Attributes",
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

    page_size = 25

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status
        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('cmdb_fields')
            self.column_exclude_list.append('cmdb_template')

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

    def on_model_change(self, form, model, is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.source_account_id = ""
        model.source_account_name = "cmdb"
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
