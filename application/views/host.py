"""
Host Model View
"""
# pylint: disable=too-many-lines
from datetime import datetime
import re
import csv
import io
from flask_login import current_user
from flask import flash, request, redirect, url_for, render_template_string, Response
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter
from flask_admin.model.template import LinkRowAction
from flask_admin.form import rules
from flask_admin.actions import action
from flask_admin.base import expose
from wtforms import HiddenField, Field, StringField, BooleanField
from wtforms.validators import Optional
from markupsafe import Markup, escape
from mongoengine.errors import DoesNotExist

# pylint: disable=import-error
from application.plugins.checkmk.models import CheckmkFolderPool
from application.plugins.checkmk import get_host_debug_data as cmk_host_debug
from application.plugins.netbox import get_device_debug_data as netbox_host_debug
from application import app
from application.views.default import DefaultModelView
from application.models.host import Host, CmdbField
from application.models.config import Config
from application.modules.log.models import LogEntry
# pylint: enable=import-error

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

FILTER_KEY_RE = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$')


def _validate_filter_key(key):
    clean_key = key.strip()
    if not FILTER_KEY_RE.fullmatch(clean_key):
        raise ValueError("Invalid filter key")
    return clean_key


def _build_safe_regex(value):
    if value == '*':
        return '.*'
    return re.escape(value).replace(r'\*', '.*')

def get_debug(hostname, mode):
    """
    Get Output for Host Debug Page
    """

    # Check permissions based on debug mode
    mode_role_mapping = {
        'checkmk_host': 'checkmk',
        'netbox_device': 'netbox',
    }

    required_role = mode_role_mapping.get(mode)
    if required_role and not current_user.has_right(required_role):
        return {'Error': f"You need the '{required_role}' role to access {mode} debug mode"}, {}

    try:
        Host.objects.get(hostname=hostname)

        output = {}
        output_rules = {}

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

    return Markup(
        f'<i class="{escape(icon_class)}" style="margin-right: 5px;">'
        f'</i>{escape(object_type_display)}'
    )

def _render_datetime(_view, _context, model, name):
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
                    {escape(entry.field_name)}
                </th>
                <td>
                    <span class="badge badge-info">{escape(entry.field_value)}</span>
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
    checkmk_labels = (
        model.cache.get('checkmk_hostattribute', {})
        .get('attributes', {}).get('all', {})
    )
    html = ""
    for key, value in model.labels.items():
        if not value:
            continue
        if checkmk_labels.get(key) == value:
            del checkmk_labels[key]
        html += (
            f'<span class="badge badge-primary mr-1" '
            f'style="margin: 2px;">'
            f'{escape(key)}:{escape(value)}</span>'
        )

    for key, value in checkmk_labels.items():
        if not value:
            continue
        if model.inventory.get(key) == value:
            continue
        html += (
            f'<span class="badge mr-1" style="margin: 2px;'
            f' background-color: rgb(43, 181, 120);">'
            f'{escape(key)}:{escape(value)}</span>'
        )


    return Markup(html)

def _render_cmdb_template(_view, _context, model, _name):
    """
    Render all assigned CMDB templates
    """
    if not model.cmdb_templates:
        return Markup("")
    parts = []
    for tmpl in model.cmdb_templates:
        header = (
            f'<caption style="caption-side:top;font-weight:bold">'
            f'{escape(tmpl.hostname)}</caption>'
        )
        rows = ''.join(
            f'<tr><th scope="row" style="width:30%;">{escape(k)}</th>'
            f'<td><span class="badge badge-info">{escape(v)}</span></td></tr>'
            for k, v in tmpl.labels.items()
        )
        parts.append(f'<table class="table table-bordered">{header}{rows}</table>')
    return Markup(''.join(parts))

def _render_cmdb_match_label(_view, _context, model, _name):
    """
    Render CMDB Match as badge label
    """
    if not model.cmdb_match:
        return Markup('<span class="text-muted">N/A</span>')
    return Markup(f'<span class="badge badge-primary">{model.cmdb_match}</span>')

class StaticLabelWidget:  # pylint: disable=too-few-public-methods
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

class StaticTemplateLabelWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Template Labels in Views
    """
    def __call__(self, field, **kwargs):
        model = field.object_data
        if not model or not hasattr(model, 'cmdb_templates') or not model.cmdb_templates:
            return Markup(
                '<div class="alert alert-info">'
                'No Templates selected</div>'
            )

        html = ''
        for template in model.cmdb_templates:
            if not hasattr(template, 'labels') or not template.labels:
                continue
            entries = [
                f'<span class="badge badge-primary">{escape(key)}</span>'
                f':<span class="badge badge-info">{escape(value)}</span>'
                for key, value in template.labels.items()
            ]
            html += (
                f'<div class="card" style="margin-bottom:4px">'
                f'<div class="card-header p-1"><strong>{escape(template.hostname)}</strong></div>'
                f'<div class="card-body p-2">{" ".join(entries)}</div></div>'
            )
        if html:
            return Markup(html)
        return Markup(
            '<div class="alert alert-warning">'
            'No Labels in Templates</div>'
        )

class StaticTemplateLabelField(Field):
    """
    Helper for Widget
    """
    widget = StaticTemplateLabelWidget()

    def _value(self):
        return str(self.data) if self.data else ''

class CmdbMatchWidget:  # pylint: disable=too-few-public-methods
    """
    Widget for CMDB Match key:value input with styling
    """
    def __call__(self, field, **kwargs):
        # Split existing value if any
        key = ""
        value = ""
        if field.data and ':' in field.data:
            key, value = field.data.split(':', 1)

        html = f'''
        <div class="cmdb-match-container" style="margin-bottom: 15px;">
            <div class="form-row align-items-center">
                <div class="col-auto">
                    <input type="text" id="cmdb_match_key"
                           value="{escape(key)}" placeholder="Key"
                           style="background-color: #2EFE9A;
                                  border-radius: 5px; padding: 8px 12px;
                                  font-weight: bold;
                                  border: 1px solid #1abc9c;
                                  margin-right: 10px; width: 150px;">
                </div>
                <div class="col-auto">
                    <input type="text" id="cmdb_match_value"
                           value="{escape(value)}" placeholder="Value"
                           style="background-color: #81DAF5;
                                  border-radius: 5px; padding: 8px 12px;
                                  font-family: monospace;
                                  border: 1px solid #3498db;
                                  width: 200px;">
                </div>
            </div>
            <input type="hidden"
                   name="{escape(field.name)}"
                   id="{escape(field.id)}"
                   value="{escape(field.data or '')}" />
            <small class="form-text text-muted">Enter Attribute which should lead to automatic match</small>
        </div>
        <script>
        function updateCmdbMatch() {{
            var key = document.getElementById('cmdb_match_key').value;
            var value = document.getElementById('cmdb_match_value').value;
            var hiddenField = document.getElementById('{escape(field.id)}');

            if (key && value) {{
                hiddenField.value = key + ':' + value;
            }} else {{
                hiddenField.value = '';
            }}
        }}

        document.getElementById('cmdb_match_key').addEventListener('input', updateCmdbMatch);
        document.getElementById('cmdb_match_value').addEventListener('input', updateCmdbMatch);
        </script>
        '''
        return Markup(html)

class CmdbMatchField(Field):
    """
    Custom field for CMDB Match key:value input
    """
    widget = CmdbMatchWidget()

    def _value(self):
        return str(self.data) if self.data else ''

class StaticLogWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Lists in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        html += "<table class='table'>"
        for line in field.data:
            html += f"<tr><td>{escape(line[:160])}</td></tr>"
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
        return query.filter(folder__icontains=value)

    def operation(self):
        return "contains"

class FilterLabelKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Label
    """

    def apply(self, query, value):
        try:
            key, value = value.split(':', 1)
            key = _validate_filter_key(key)
            value = value.strip()

            # Filter for None values, but only if key exists
            if value.lower() == 'none':
                pipeline = {
                    "$and": [
                        {f"labels.{key}": None},
                        {f"labels.{key}": {"$exists": True}}
                    ]
                }
                return query.filter(__raw__=pipeline)

            org_value = None

            try:
                org_value = int(value)
            except ValueError:
                pass

            safe_regex = _build_safe_regex(value)

            if org_value is not None:
                pipeline = {
                        "$or": [
                        {f'labels.{key}': {"$regex": safe_regex, "$options": "i"}},
                        {f'labels.{key}': org_value}
                    ]
                }

            else:
                pipeline = {
                        f'labels.{key}': {"$regex": safe_regex, "$options": "i"},
                }
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash('danger', error)
        return False

    def operation(self):
        return "regex search"

class FilterInventoryKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Inventory
    """

    def apply(self, query, value):
        try:
            key, value = value.split(':', 1)
            key = _validate_filter_key(key)
            value = value.strip()

            # Filter for None values, but only if key exists
            if value.lower() == 'none':
                pipeline = {
                    "$and": [
                        {f"inventory.{key}": None},
                        {f"inventory.{key}": {"$exists": True}}
                    ]
                }
                return query.filter(__raw__=pipeline)

            org_value = None

            try:
                org_value = int(value)
            except ValueError:
                pass

            safe_regex = _build_safe_regex(value)

            if org_value is not None:
                pipeline = {
                        "$or": [
                        {f'inventory.{key}': {"$regex": safe_regex, "$options": "i"}},
                        {f'inventory.{key}': org_value}
                    ]
                }
            else:
                pipeline = {
                        f'inventory.{key}': {"$regex": safe_regex, "$options": "i"},
                }
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash('danger', error)
        return False

    def operation(self):
        return "regex search"

def format_log(_v, _c, m, _p):
    """ Format Log view"""
    html = "<ul>"
    for entry in m.log:
        suffix = '...' if len(entry) > 200 else ''
        html += f"<li>{entry[:200]}{suffix}</li>"
    html += "</ul>"

    if m.log:
        modal_id = f"logModal_{m.id}"

        # Find LogEntry records where hostname is in affected_hosts (StringField)
        related_log_entries = LogEntry.objects(
            affected_hosts__in=m.hostname
        ).order_by('-datetime')

        html += (
            f'<button type="button" '
            f'class="btn btn-sm btn-outline-primary" '
            f'data-toggle="modal" '
            f'data-target="#{modal_id}">'
            f'View Full Logs</button>'
            f'<div class="modal fade" id="{modal_id}" '
            f'tabindex="-1" role="dialog" '
            f'aria-labelledby="{modal_id}Label" '
            f'aria-hidden="true">'
            f'<div class="modal-dialog modal-xl" '
            f'role="document"><div class="modal-content">'
            f'<div class="modal-header">'
            f'<h5 class="modal-title" '
            f'id="{modal_id}Label">'
            f'Full Logs for: {m.hostname}</h5>'
            f'<button type="button" class="close" '
            f'data-dismiss="modal" aria-label="Close">'
            f'<span aria-hidden="true">&times;</span>'
            f'</button></div>'
            f'<div class="modal-body">'
            f'<h6 class="mb-3">'
            f'<i class="fa fa-server"></i> '
            f'Host-specific Logs</h6>'
            f'<div class="log-container" '
            f'style="max-height: 40vh; overflow-y: auto; '
            f'font-family: monospace; font-size: 0.9em; '
            f'margin-bottom: 20px;">'
        )
        for log_entry in m.log:
            # HTML escape the log entry content
            escaped_entry = escape(str(log_entry))
            html += (
                f'<div class="log-entry mb-2 p-2" '
                f'style="background-color: #f8f9fa; '
                f'border-left: 3px solid #007bff; '
                f'white-space: pre-wrap; '
                f'word-wrap: break-word;">'
                f'{escaped_entry}</div>'
            )

        html += (
            f'</div><div class="mb-3">'
            f'<small class="text-muted">'
            f'Host-specific log entries: {len(m.log)}'
            f'</small></div>'
        )

        # Add related LogEntry records
        if related_log_entries:
            html += (
                '<h6 class="mb-3">'
                '<i class="fa fa-list"></i> '
                'Related System Logs</h6>'
                '<div class="log-container" '
                'style="max-height: 40vh; '
                'overflow-y: auto; '
                'font-family: monospace; '
                'font-size: 0.9em;">'
            )
            for log_entry in related_log_entries[:50]:
                escaped_message = escape(str(log_entry.message))
                timestamp = (
                    log_entry.datetime.strftime(
                        '%Y-%m-%d %H:%M:%S'
                    )
                    if log_entry.datetime else 'N/A'
                )

                # Determine color based on error status
                if log_entry.has_error:
                    level_color = '#dc3545'
                    level_text = 'ERROR'
                else:
                    level_color = '#007bff'
                    level_text = 'INFO'

                html += (
                    f'<div class="log-entry mb-2 p-2" '
                    f'style="background-color: #f8f9fa; '
                    f'border-left: 3px solid '
                    f'{level_color}; '
                    f'white-space: pre-wrap; '
                    f'word-wrap: break-word;">'
                    f'<small class="text-muted">'
                    f'[{timestamp}] '
                    f'<span style="color: {level_color};'
                    f' font-weight: bold;">'
                    f'{level_text}</span></small>'
                    f'<br>{escaped_message}</div>'
                )

            num = len(related_log_entries)
            html += (
                f'</div><div class="mt-3">'
                f'<small class="text-muted">'
                f'Related system log entries: {num}'
                f' (showing most recent 50)'
                f'</small></div>'
            )

        html += (
            '</div><div class="modal-footer">'
            '<button type="button" '
            'class="btn btn-secondary" '
            'data-dismiss="modal">Close</button>'
            '</div></div></div></div>'
        )

    return Markup(html)

def format_cache(_v, _c, m, _p):
    """ Format cache"""
    if not m.cache:
        return Markup('<span class="text-muted">No cache data</span>')

    # Show summary (number of cache entries)
    cache_count = len(m.cache)
    html = f'<span class="text-muted">{cache_count} cache entrie(s)</span>'

    if m.cache:
        cache_id = f"cache_{m.id}"

        html += (
            f'<br><button type="button" '
            f'class="btn btn-sm btn-outline-primary" '
            f'onclick="toggleCache(\'{cache_id}\')">'
            f'<i class="fa fa-database"></i> '
            f'View Cache Details</button>'
            f'<div id="{cache_id}" '
            f'style="display: none; margin-top: 10px;">'
            f'<div class="border rounded p-3" '
            f'style="background-color: #f8f9fa;">'
            f'<table class="table table-sm table-striped">'
        )

        for key, value in m.cache.items():
            html += f'<tr><th colspan="2" class="bg-light">{key}</th></tr>'
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    # Truncate very long values
                    if isinstance(sub_value, str) and len(sub_value) > 100:
                        display_value = sub_value[:100] + '...'
                    else:
                        display_value = str(sub_value)
                    html += (
                        f'<tr><td class="pl-4" '
                        f'style="width: 30%;">'
                        f'{sub_key}</td>'
                        f'<td>{display_value}</td></tr>'
                    )
            else:
                # If value is not a dict, show it directly
                if isinstance(value, str) and len(value) > 100:
                    display_value = value[:100] + '...'
                else:
                    display_value = str(value)
                html += (
                    f'<tr><td class="pl-4" '
                    f'style="width: 30%;">Value</td>'
                    f'<td>{display_value}</td></tr>'
                )

        html += '''
                </table>
            </div>
        </div>

        <script>
        function toggleCache(cacheId) {
            var cacheDiv = document.getElementById(cacheId);
            var button = event.target;
            if (!button.classList.contains('btn')) {
                button = button.closest('.btn');
            }

            if (cacheDiv.style.display === 'none') {
                cacheDiv.style.display = 'block';
                button.innerHTML = '<i class="fa fa-database"></i> Hide Cache Details';
            } else {
                cacheDiv.style.display = 'none';
                button.innerHTML = '<i class="fa fa-database"></i> View Cache Details';
            }
        }
        </script>
        '''

    return Markup(html)

def format_labels(_v, _c, m, _p):
    """ Format Labels view"""
    html = "<table>"
    for key, value in m.labels.items():
        html += f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>"
    html += "</table>"
    return Markup(html)

def format_inventory(_v, _c, m, _p):
    """ Format Inventory view"""
    html = "<table>"
    for key, value in m.inventory.items():
        html += f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>"
    html += "</table>"
    return Markup(html)

def format_labels_export(_v, _c, m, _p):
    """ Format Labels view"""
    labels = []
    for entry in m.labels:
        labels.append(f"{entry.key}:{entry.value}")
    return Markup(", ".join(labels))

def format_inventory_export(_v, _c, m, _p):
    """ Format Inventory view"""
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
        'hostname', 'no_autodelete', 'inventory', 'labels', 'cache'
    ]

    column_exclude_list = [
        'source_account_id',
        'cmdb_templates',
        'sync_id',
        'cmdb_match',
        'last_import_id',
        'create_time',
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
        'cmdb_match': _render_cmdb_match_label,
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
        'hostname': StringField,
        'cmdb_match': CmdbMatchField,
    }

    form_rules = [
        rules.HTML('''
        <style>
        [id^="cmdb_fields-"] legend { border: none !important; padding: 0 !important; margin: 0 0 4px 0 !important; }
        [id^="cmdb_fields-"] legend small { font-size: 0 !important; }
        [id^="cmdb_fields-"] legend small .pull-right { font-size: 1rem !important; }
        [id^="cmdb_fields-"] .card {
            margin-bottom: 8px !important;
            padding: 10px !important;
            background-color: #f8f9fa !important;
            border-radius: 8px !important;
        }
        [id^="cmdb_fields-"] label { display: none !important; }
        [id^="cmdb_fields-"] .form-group { margin-bottom: 0 !important; }
        [id^="cmdb_fields-"] .inline-field { margin-bottom: 8px !important; }
        </style>
        '''),
        rules.Field('hostname'),
        rules.Field('object_type'),
        rules.FieldSet(('cmdb_fields',), "CMDB Fields"),
    ]

    form_args = {
        "hostname": {
            "label": 'Object Name'
        },
        "object_type": {
            "label": 'Object Type'
        },
        "cmdb_match": {
            "label": 'CMDB Match Rule'
        }
    }

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {
                            'style': (
                                'background-color: #2EFE9A; '
                                'border-radius: 5px; '
                                'padding: 6px 10px; '
                                'margin-right: 5px; '
                                'font-weight: bold; '
                                'border: 1px solid #1abc9c; '
                                'width: 220px;'
                            ),
                            'size': 20,
                            'placeholder': 'Key'
                        },
                        'field_value': {
                            'style': (
                                'background-color: #81DAF5; '
                                'border-radius: 5px; '
                                'padding: 6px 10px; '
                                'font-family: monospace; '
                                'margin-left: 5px; '
                                'border: 1px solid #3498db; '
                                'width: 450px;'
                            ),
                            'size': 40,
                            'placeholder': 'Value'
                        },
                    },
                    'form_rules': [
                        rules.HTML(
                            '<div class="form-row '
                            'align-items-center" '
                            'style="margin-bottom: 5px; '
                            'margin-top: 0;">'
                        ),
                        rules.HTML('<div class="col-auto">'),
                        rules.Field('field_name'),
                        rules.HTML('</div>'),
                        rules.HTML(
                            '<div class="col-auto">'
                            '<span style="font-size: 16px;'
                            ' margin: 0 3px;">:</span>'
                            '</div>'
                        ),
                        rules.HTML('<div class="col-auto">'),
                        rules.Field('field_value'),
                        rules.HTML('</div>'),
                        rules.HTML('</div>'),
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
        return Host.objects(is_object=True, object_type__ne='template')

    def on_model_change(self, form, model, _is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.is_object = True
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
        # Set Extra Fields
        new_labels = {x['field_name']: x['field_value'] for x in form.cmdb_fields.data}
        #model.object_type = 'template'

        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('objects')

class TemplateModelView(ObjectModelView):
    """Template Model View for CMDB templates."""

    form_rules = [
        rules.HTML('''
        <style>
        [id^="cmdb_fields-"] legend { border: none !important; padding: 0 !important; margin: 0 0 4px 0 !important; }
        [id^="cmdb_fields-"] legend small { font-size: 0 !important; }
        [id^="cmdb_fields-"] legend small .pull-right { font-size: 1rem !important; }
        [id^="cmdb_fields-"] .card {
            margin-bottom: 8px !important;
            padding: 10px !important;
            background-color: #f8f9fa !important;
            border-radius: 8px !important;
        }
        [id^="cmdb_fields-"] label { display: none !important; }
        [id^="cmdb_fields-"] .form-group { margin-bottom: 0 !important; }
        [id^="cmdb_fields-"] .inline-field { margin-bottom: 8px !important; }
        </style>
        '''),
        rules.Field('hostname'),
        rules.FieldSet(('cmdb_fields', 'cmdb_match'), "CMDB Fields"),
    ]

    column_exclude_list = [
        'source_account_id',
        'cmdb_templates',
        'sync_id',
        'object_type',
        'last_import_seen',
        'create_time',
        'last_import_id',
        'last_import_sync',
        'available',
        'no_autodelete',
        'source_account_name',
        'labels',
        'inventory',
        'log',
        'folder',
        'raw',
        'cache',
        'is_object',
    ]

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True, object_type="template")

    def on_model_change(self, form, model, _is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.is_object = True
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
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

    page_size = app.config['HOST_PAGESIZE']

    column_details_list = [
        'hostname', 'folder', 'no_autodelete', 'available',
        'labels', 'inventory', 'cmdb_templates', 'log',
        'last_import_seen', 'last_import_sync', 'create_time', 'last_import_id',
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
        'cmdb_match',
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
        'cmdb_templates': _render_cmdb_template,
        'last_import_seen': _render_datetime,
        'last_import_sync': _render_datetime,
        'create_time': _render_datetime,
        'object_type': _render_object_type_icon,
    }

    column_formatters_export = {
        'hostname': get_rule_json
    }

    column_labels = {
        'source_account_name': "Account",
        'folder': "CMK Pool Folder",
        'cmdb_templates': "CMDB",
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

    form_args = {
        'cmdb_templates': {
            'validators': [Optional()]
        }
    }

    form_rules = [
        rules.FieldSet((
            rules.Field('hostname'),
            rules.NestedRule((
                'object_type', 'available',
                'cmdb_templates', 'labels_from_template',
            )),
            ), "CMDB Options"),
        rules.FieldSet(('cmdb_fields',), "CMDB Fields"),
        #rules.FieldSet(('inventory', 'log'), "Data"),
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
                        rules.HTML(
                            '<div class="form-row '
                            'align-items-center" '
                            'style="margin-bottom: 8px;">'
                        ),
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
            self.column_exclude_list.append('cmdb_templates')

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
        """Scaffold form with extra CMDB fields."""
        form_class = super().scaffold_form()
        form_class.labels_from_template = StaticTemplateLabelField()

        # Filter cmdb_templates to show only template objects
        if hasattr(form_class, 'cmdb_templates'):
            form_class.cmdb_templates.kwargs['queryset'] = Host.objects(object_type='template')

        return form_class

    def edit_form(self, obj=None):
        """Build edit form with template labels and CMDB fields."""
        form = super().edit_form(obj)
        if obj and hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj

        if hasattr(form, 'cmdb_templates'):
            form.cmdb_templates.queryset = Host.objects(object_type='template')

        if obj and hasattr(form, 'cmdb_fields'):
            existing_field_names = {
                str(getattr(entry, 'field_name', None).data)
                for entry in form.cmdb_fields.entries
                if getattr(getattr(entry, 'field_name', None), 'data', None)
            }
            for label_key, label_value in (obj.labels or {}).items():
                if label_key not in existing_field_names:
                    form.cmdb_fields.append_entry({
                        'field_name': label_key,
                        'field_value': str(label_value) if label_value is not None else ''
                    })
                    existing_field_names.add(label_key)

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
        """Build create form with template labels and CMDB fields."""
        form = super().create_form(obj)
        if hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj
        if hasattr(form, 'cmdb_templates'):
            form.cmdb_templates.queryset = Host.objects(object_type='template')
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


    def on_model_change(self, form, model, _is_created):
        """
        Model Changes when saved in GUI -> CMDB Mode
        """
        model.last_import_sync = datetime.now()
        model.last_import_seen = datetime.now()
        model.cache = {}
        model.source_account_id = ""
        model.source_account_name = "cmdb"
        model.no_autodelete = True
        model.cmdb_templates = form.cmdb_templates.data or []
        # Set Extra Fields
        cmdb_fields = app.config['CMDB_MODELS'].get(form.object_type.data, {})
        cmdb_fields.update(app.config['CMDB_MODELS']['all'])
        new_labels = {
            entry['field_name']: entry['field_value']
            for entry in form.cmdb_fields.data
            if entry.get('field_name')
        }

        existing_labels = model.labels or {}
        for label_key, label_value in existing_labels.items():
            if label_key not in new_labels:
                new_labels[label_key] = label_value

        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

        existing_cmdb_fields = {
            field.field_name for field in (model.cmdb_fields or [])
            if getattr(field, 'field_name', None)
        }
        for label_key, label_value in new_labels.items():
            if label_key not in existing_cmdb_fields:
                new_field = CmdbField()
                new_field.field_name = label_key
                new_field.field_value = str(label_value) if label_value is not None else ''
                model.cmdb_fields.append(new_field)
                existing_cmdb_fields.add(label_key)

        for key in cmdb_fields:
            if key not in new_labels:
                new_field = CmdbField()
                new_field.field_name = key
                model.cmdb_fields.append(new_field)
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('cmdb_fields')
            self.column_exclude_list.append('cmdb_templates')

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
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',')]
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
                    # Append template if not already in the list
                    existing_ids = [t.id for t in host.cmdb_templates]
                    if template.id not in existing_ids:
                        host.cmdb_templates.append(template)

                    # Apply the same logic as on_model_change
                    host.last_import_sync = datetime.now()
                    host.last_import_seen = datetime.now()
                    host.cache = {}
                    host.source_account_name = "cmdb"

                    # Set Extra Fields from CMDB config
                    cmdb_fields = app.config['CMDB_MODELS'].get(host.object_type, {})
                    cmdb_fields.update(app.config['CMDB_MODELS']['all'])

                    # Create labels from existing cmdb_fields
                    new_labels = {
                        x.field_name: x.field_value
                        for x in host.cmdb_fields
                        if x.field_value
                    }

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

        except Exception as e:  # pylint: disable=broad-exception-caught
            flash(f'Error applying template: {str(e)}', 'error')

        return redirect(url_for('.index_view'))

    def get_template_list(self):
        """Get available CMDB templates for the action form"""
        try:
            templates = Host.objects(is_object=True, object_type='template')
            return list(templates)
        except Exception:  # pylint: disable=broad-exception-caught
            return []

    @expose('/csv')
    def export_csv(self):  # pylint: disable=too-many-locals
        """
        Export all hosts as CSV
        """
        if not current_user.is_authenticated or not current_user.has_right('host'):
            return Response("Unauthorized", status=401)


        try:
            config = Config.objects().first()
            export_labels = (
                config.export_labels_list
                if config and config.export_labels_list
                else []
            )
            export_inventory = (
                config.export_inventory_list
                if config and config.export_inventory_list
                else []
            )
        except Exception:  # pylint: disable=broad-exception-caught
            export_labels = []
            export_inventory = []

        # Create CSV string in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write CSV header
        headers = [
            'hostname',
            'object_type',
            'available',
            'source_account_name',
            'folder',
            'last_import_seen',
            'last_import_sync',
            'no_autodelete'
        ]

        # Add configured label fields
        for label_field in export_labels:
            headers.append(f'label_{label_field}')

        # Add configured inventory fields
        for inventory_field in export_inventory:
            headers.append(f'inventory_{inventory_field}')

        writer.writerow(headers)

        # Get all hosts (excluding objects/templates)
        hosts = Host.objects(is_object__ne=True).order_by('hostname')

        # Write host data
        for host in hosts:
            row = [
                host.hostname or '',
                host.object_type or '',
                host.available if host.available is not None else '',
                host.source_account_name or '',
                host.folder or '',
                host.last_import_seen.strftime(
                    '%Y-%m-%d %H:%M:%S'
                ) if host.last_import_seen else '',
                host.last_import_sync.strftime(
                    '%Y-%m-%d %H:%M:%S'
                ) if host.last_import_sync else '',
                host.no_autodelete if host.no_autodelete is not None else ''
            ]

            # Add configured label values
            for label_field in export_labels:
                value = host.labels.get(label_field, '') if host.labels else ''
                row.append(value)

            # Add configured inventory values
            for inventory_field in export_inventory:
                value = host.inventory.get(inventory_field, '') if host.inventory else ''
                row.append(value)

            writer.writerow(row)

        # Create response with CSV content
        csv_content = output.getvalue()
        output.close()

        # Generate filename with timestamp
        now = datetime.now()
        filename = f"hosts_export_{now.strftime('%Y%m%d_%H%M%S')}.csv"

        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

        return response
