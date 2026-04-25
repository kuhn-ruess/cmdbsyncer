"""
Host Model View
"""
# pylint: disable=too-many-lines,duplicate-code
from datetime import datetime
import re
import csv
import io
from flask_login import current_user
from flask import flash, request, redirect, url_for, render_template, Response
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
from application.plugins.ansible import get_ansible_debug_data as ansible_host_debug
from application.plugins.idoit import get_idoit_debug_data as idoit_host_debug
from application.plugins.vmware import get_vmware_debug_data as vmware_host_debug
from application import app
from application.views.default import DefaultModelView
from application.models.host import Host, CmdbField, HostLabelChange
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


def _compile_filter_regex(value):
    """
    Validate a user-supplied regex for a Key:Value label/inventory
    filter. The filter operation is advertised as "regex search", so
    the raw value is used verbatim — we only size-limit it and confirm
    it compiles, matching the hostname-filter precedent.
    """
    if len(value) > 500:
        raise ValueError("Filter value too long")
    re.compile(value)
    return value

def get_debug(hostname, mode):
    """
    Get Output for Host Debug Page
    """

    # Check permissions based on debug mode
    mode_role_mapping = {
        'checkmk_host': 'checkmk',
        'netbox_device': 'netbox',
        'ansible_host': 'ansible',
        'idoit_host': 'idoit',
        'vmware_host': 'vmware',
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
            'ansible_host': ansible_host_debug,
            'idoit_host': idoit_host_debug,
            'vmware_host': vmware_host_debug,
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
    return Markup(escape(str(value)))

_LABEL_BADGE_STYLE = (
    'display: inline-block; max-width: 280px; '
    'overflow: hidden; text-overflow: ellipsis; '
    'white-space: nowrap; vertical-align: middle; '
    'margin: 2px;'
)
_LABEL_WRAPPER_STYLE = 'max-width: 600px;'


def _render_cmdb_fields_preview(_view, _context, model, _name):
    """
    Compact badge preview of CMDB fields for the list view. Mirrors
    the label-preview rendering so the host list stays uniform.
    """
    if not model.cmdb_fields:
        return Markup("")
    html = f'<div style="{_LABEL_WRAPPER_STYLE}">'
    for entry in model.cmdb_fields:
        if not entry.field_value:
            continue
        text = f"{entry.field_name}:{entry.field_value}"
        html += (
            f'<span class="badge badge-info mr-1" '
            f'style="{_LABEL_BADGE_STYLE}" title="{escape(text)}">'
            f'{escape(text)}</span>'
        )
    html += '</div>'
    return Markup(html)


def _render_cmdb_fields(_view, _context, model, _name):
    """
    Detail-view rendering of CMDB fields — same Key / Value / Type
    table as Labels and Inventory.
    """
    if not model.cmdb_fields:
        return Markup("")
    items = {
        entry.field_name: entry.field_value
        for entry in model.cmdb_fields
        if entry.field_value
    }
    return _format_keyvalue_with_type(items)


_LABEL_GRID_CSS = (
    '<style>'
    '.cmdb-label-grid{display:grid;grid-template-columns:1fr 1fr;'
    'gap:2px 20px;margin:4px 0;}'
    '@media (max-width:992px){.cmdb-label-grid{grid-template-columns:1fr;}}'
    '.cmdb-label-row{display:flex;align-items:center;gap:6px;padding:2px 0;'
    'min-width:0;border-bottom:1px solid #f0f0f0;}'
    '.cmdb-label-row .lbl-src{flex:0 0 auto;font-size:0.72rem;'
    'padding:1px 6px;border-radius:3px;white-space:nowrap;}'
    '.cmdb-label-row .lbl-key{flex:0 0 auto;font-weight:bold;'
    'color:#1abc9c;}'
    '.cmdb-label-row .lbl-val{flex:1 1 auto;font-family:monospace;'
    'color:#2c3e50;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
    '.cmdb-label-row .lbl-type{flex:0 0 auto;font-size:0.7rem;'
    'padding:1px 6px;border-radius:3px;background:#6c757d;color:#fff;'
    'white-space:nowrap;font-family:monospace;}'
    '.cmdb-label-row .lbl-src.src-manual{background:#e8f6fd;color:#2980b9;}'
    '.cmdb-label-row .lbl-src.src-template{background:#eaf7ea;color:#1e8449;}'
    '</style>'
)


def _render_labels_with_origin(_view, _context, model, _name):
    """
    Compact read-only detail rendering of a host's labels grouped by
    origin. Each row shows a small badge ("manual" or the template
    hostname), the key, the value, and a BSON-type badge (so admins
    can tell a string `"True"` from a BSON bool `True` — they match
    different filters).
    """
    manual = model.labels or {}
    templates = []
    for tmpl in (model.cmdb_templates or []):
        if getattr(tmpl, 'labels', None):
            templates.append((tmpl.hostname, dict(tmpl.labels)))

    if not manual and not templates:
        return Markup('<em class="text-muted">No labels.</em>')

    rows = []
    for key in sorted(manual.keys(), key=str.lower):
        rows.append(('manual', '', key, manual[key]))
    for tmpl_name, tmpl_labels in templates:
        for key in sorted(tmpl_labels.keys(), key=str.lower):
            rows.append(('template', tmpl_name, key, tmpl_labels[key]))

    html = [_LABEL_GRID_CSS, '<div class="cmdb-label-grid">']
    for origin, src_name, key, value in rows:
        if origin == 'manual':
            src_badge = (
                '<span class="lbl-src src-manual" '
                'title="Maintained manually on this host">manual</span>'
            )
        else:
            src_badge = (
                f'<span class="lbl-src src-template" '
                f'title="From template {escape(src_name)}">'
                f'{escape(src_name)}</span>'
            )
        value_str = '' if value is None else str(value)
        type_name = _value_type_name(value)
        html.append(
            '<div class="cmdb-label-row">'
            f'{src_badge}'
            f'<span class="lbl-key">{escape(str(key))}</span>'
            f'<span class="lbl-val" title="{escape(value_str)}">'
            f'{escape(value_str)}</span>'
            f'<span class="lbl-type" title="BSON type">{escape(type_name)}</span>'
            '</div>'
        )
    html.append('</div>')
    return Markup(''.join(html))


def _render_labels(_view, _context, model, _name):
    """
    Render Labels
    """
    if not model.labels:
        return Markup("")
    # Truncation + `title` tooltip keeps customer hosts with very long
    # label values from stretching the row off-screen; the full value
    # is still available on hover.
    checkmk_labels = (
        model.cache.get('checkmk_hostattribute', {})
        .get('attributes', {}).get('all', {})
    )
    html = f'<div style="{_LABEL_WRAPPER_STYLE}">'
    for key, value in model.labels.items():
        if not value:
            continue
        if checkmk_labels.get(key) == value:
            del checkmk_labels[key]
        text = f"{key}:{value}"
        html += (
            f'<span class="badge badge-primary mr-1" '
            f'style="{_LABEL_BADGE_STYLE}" title="{escape(text)}">'
            f'{escape(text)}</span>'
        )

    for key, value in checkmk_labels.items():
        if not value:
            continue
        if model.inventory.get(key) == value:
            continue
        text = f"{key}:{value}"
        html += (
            f'<span class="badge mr-1" '
            f'style="{_LABEL_BADGE_STYLE} '
            f'background-color: rgb(43, 181, 120);" '
            f'title="{escape(text)}">'
            f'{escape(text)}</span>'
        )

    html += '</div>'
    return Markup(html)

def _render_cmdb_template(_view, _context, model, _name):
    """
    Detail-view rendering of assigned CMDB templates — one
    Key / Value / Type table per template, headed by the template
    hostname. Same visual style as Labels and Inventory.
    """
    if not model.cmdb_templates:
        return Markup("")
    html = ""
    for tmpl in model.cmdb_templates:
        html += (
            f'<h6 style="margin-top: 8px; font-weight: bold;">'
            f'{escape(tmpl.hostname)}</h6>'
        )
        html += str(_format_keyvalue_with_type(tmpl.labels or {}))
    return Markup(html)


def _template_edit_url(tmpl):
    """
    Build the admin edit URL for a CMDB template. TemplateModelView
    is registered with `endpoint="Objects Templates"` — use `url_for`
    so the URL stays correct if the endpoint is renamed later; fall
    back to an empty string and render without a link on failure.
    """
    try:
        return url_for('Objects Templates.edit_view', id=str(tmpl.id))
    except Exception:  # pylint: disable=broad-exception-caught
        return ''


def _render_cmdb_template_preview(_view, _context, model, _name):
    """
    Compact badge preview of assigned CMDB templates for the list
    view — just the template hostnames, same badge style as the
    label preview. Each badge links to the template's edit page.
    """
    if not model.cmdb_templates:
        return Markup("")
    html = f'<div style="{_LABEL_WRAPPER_STYLE}">'
    for tmpl in model.cmdb_templates:
        name = escape(tmpl.hostname)
        badge = (
            f'<span class="badge badge-dark mr-1" '
            f'style="{_LABEL_BADGE_STYLE}" '
            f'title="{name}">'
            f'<i class="fa fa-file"></i> {name}</span>'
        )
        href = _template_edit_url(tmpl)
        if href:
            html += (
                f'<a href="{escape(href)}" '
                f'style="text-decoration: none;">{badge}</a>'
            )
        else:
            html += badge
    html += '</div>'
    return Markup(html)

def _render_cmdb_match_label(_view, _context, model, _name):
    """
    Render CMDB Match as badge label
    """
    if not model.cmdb_match:
        return Markup('<span class="text-muted">N/A</span>')
    return Markup(f'<span class="badge badge-primary">{escape(model.cmdb_match)}</span>')

class StaticLabelWidget:  # pylint: disable=too-few-public-methods
    """
    Design for Lablels in Views
    """
    def __call__(self, field, **kwargs):
        html = '<div class="card"><div class="card-body">'
        entries = []
        for key, value in field.data.items():
            html_entry = ""
            html_entry += f'<span class="badge badge-primary">{escape(key)}</span>:'
            html_entry += f'<span class="badge badge-info">{escape(value)}</span>'
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
    _INTRO = (
        '<p class="text-muted small" style="margin-bottom:6px;">'
        '<i class="fa fa-info-circle"></i> '
        'These labels originate from the templates assigned above. They '
        'are read-only here and are merged into the host labels at export '
        'time — manual labels below win on conflicts.'
        '</p>'
    )

    def __call__(self, field, **kwargs):
        model = field.object_data
        if not model or not hasattr(model, 'cmdb_templates') or not model.cmdb_templates:
            return Markup(
                self._INTRO
                + '<div class="alert alert-info">'
                'No templates assigned — no template labels apply.'
                '</div>'
            )

        html = self._INTRO
        had_entries = False
        for template in model.cmdb_templates:
            if not hasattr(template, 'labels') or not template.labels:
                continue
            had_entries = True
            entries = [
                f'<span class="badge badge-primary">{escape(key)}</span>'
                f':<span class="badge badge-info">{escape(value)}</span>'
                for key, value in template.labels.items()
            ]
            html += (
                f'<div class="card" style="margin-bottom:4px; '
                f'border-left: 3px solid #3498db;">'
                f'<div class="card-header p-1" '
                f'style="background-color:#eef6fc;">'
                f'<i class="fa fa-clone"></i> '
                f'<strong>{escape(template.hostname)}</strong>'
                f'</div>'
                f'<div class="card-body p-2">{" ".join(entries)}</div>'
                f'</div>'
            )
        if had_entries:
            return Markup(html)
        return Markup(
            self._INTRO
            + '<div class="alert alert-warning">'
            'Assigned templates carry no labels.'
            '</div>'
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
        if len(value) > 1000:
            return query.filter(hostname=None)
        try:
            regex = re.compile(value)
        except re.error:
            return query.filter(hostname=None)
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

def _build_keyvalue_pipeline(field, value):
    """
    Build a MongoDB `$or` pipeline for a "key:value" label/inventory
    filter. The string branch uses `$regex` so users can actually pass
    regex syntax (the filter is advertised as "regex search"); the
    numeric and boolean branches use exact equality, because BSON
    numbers and booleans are **not** string-matchable with `$regex` —
    which is why `input_monitoring:True` used to find nothing.
    """
    regex_value = _compile_filter_regex(value)
    or_clauses = [{field: {"$regex": regex_value, "$options": "i"}}]

    try:
        or_clauses.append({field: int(value)})
    except ValueError:
        pass

    lower = value.lower()
    if lower in ('true', 'yes'):
        or_clauses.append({field: True})
    elif lower in ('false', 'no'):
        or_clauses.append({field: False})

    if len(or_clauses) == 1:
        return or_clauses[0]
    return {"$or": or_clauses}


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

            pipeline = _build_keyvalue_pipeline(f'labels.{key}', value)
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash(str(error), 'danger')
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

            pipeline = _build_keyvalue_pipeline(f'inventory.{key}', value)
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash(str(error), 'danger')
        return False

    def operation(self):
        return "regex search"

def format_log(_v, _c, m, _p):
    """ Format Log view"""
    html = "<ul>"
    for entry in m.log:
        suffix = '...' if len(entry) > 200 else ''
        html += f"<li>{escape(entry[:200])}{escape(suffix)}</li>"
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
            html += f'<tr><th colspan="2" class="bg-light">{escape(key)}</th></tr>'
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
                        f'{escape(sub_key)}</td>'
                        f'<td>{escape(display_value)}</td></tr>'
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
                    f'<td>{escape(display_value)}</td></tr>'
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

def _value_type_name(value):
    """
    Human-friendly Python type name, treating `bool` as its own type
    (rather than the `int` subclass it technically is) — that is the
    distinction users care about when they wonder why
    `input_monitoring:True` does or doesn't match a filter.
    """
    if isinstance(value, bool):
        return 'bool'
    return type(value).__name__


def _format_keyvalue_with_type(items):
    """Shared Key / Value / Type table for the detail view."""
    html = (
        '<table class="table table-sm table-bordered" '
        'style="max-width: 800px;">'
        '<thead><tr><th>Key</th><th>Value</th>'
        '<th style="width: 110px;">Type</th></tr></thead><tbody>'
    )
    for key, value in (items or {}).items():
        display = '' if value is None else str(value)
        html += (
            f'<tr><th scope="row">{escape(key)}</th>'
            f'<td>{escape(display)}</td>'
            f'<td><span class="badge badge-secondary">'
            f'{escape(_value_type_name(value))}</span></td></tr>'
        )
    html += '</tbody></table>'
    return Markup(html)


def format_labels(_v, _c, m, _p):
    """ Format Labels view"""
    return _format_keyvalue_with_type(m.labels)

def format_inventory(_v, _c, m, _p):
    """ Format Inventory view"""
    return _format_keyvalue_with_type(m.inventory)


_LOG_LIST_CSS = (
    '<style>'
    '.cmdb-log-list{max-height:40vh;overflow-y:auto;border:1px solid #e9ecef;'
    'border-radius:6px;background:#fbfcfd;padding:4px 6px;}'
    '.cmdb-log-row{display:flex;gap:8px;align-items:baseline;'
    'padding:3px 4px;border-bottom:1px solid #eef1f4;'
    'font-family:ui-monospace,monospace;font-size:0.85rem;}'
    '.cmdb-log-row:last-child{border-bottom:none;}'
    '.cmdb-log-row .log-ts{flex:0 0 auto;color:#6c757d;'
    'font-variant-numeric:tabular-nums;}'
    '.cmdb-log-row .log-msg{flex:1 1 auto;min-width:0;color:#2c3e50;'
    'white-space:pre-wrap;word-wrap:break-word;}'
    '.cmdb-log-meta{margin-top:6px;font-size:0.8rem;color:#6c757d;}'
    '</style>'
)

_LOG_TS_RE = re.compile(
    r'^\s*(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\s*[-:]?\s*(?P<rest>.*)$'
)


def _render_log_grid(_view, _context, model, _name):
    """
    Detail-view log rendering in a compact scrollable list. Visually
    matches the label/inventory grid: light card background, monospace
    rows, timestamp-prefix split out so it doesn't crowd the message.
    """
    entries = list(model.log or [])
    if not entries:
        return Markup('<em class="text-muted">No log entries.</em>')

    html = [_LOG_LIST_CSS, '<div class="cmdb-log-list">']
    # Newest first — the underlying log is append-only and users
    # overwhelmingly look for the latest event.
    for entry in reversed(entries):
        text = str(entry)
        match = _LOG_TS_RE.match(text)
        if match:
            ts = match.group('ts')
            rest = match.group('rest')
        else:
            ts = ''
            rest = text
        html.append(
            '<div class="cmdb-log-row">'
            + (f'<span class="log-ts">{escape(ts)}</span>' if ts else '')
            + f'<span class="log-msg">{escape(rest)}</span>'
            '</div>'
        )
    html.append('</div>')
    html.append(
        f'<div class="cmdb-log-meta">Showing all {len(entries)} entry(ies).</div>'
    )
    return Markup(''.join(html))


_INVENTORY_GRID_CSS = (
    '<style>'
    '.cmdb-inv-grid{display:grid;grid-template-columns:1fr;'
    'gap:2px 0;margin:4px 0;}'
    '.cmdb-inv-grid .cmdb-label-row{display:flex;align-items:center;gap:6px;'
    'padding:2px 0;min-width:0;border-bottom:1px solid #f0f0f0;}'
    '.cmdb-inv-grid .lbl-src{flex:0 0 auto;font-size:0.72rem;'
    'padding:1px 6px;border-radius:3px;white-space:nowrap;'
    'background:#f1f3f5;color:#6c757d;}'
    '.cmdb-inv-grid .lbl-key{flex:0 0 auto;font-weight:bold;color:#1abc9c;}'
    '.cmdb-inv-grid .lbl-val{flex:1 1 auto;font-family:monospace;'
    'color:#2c3e50;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
    '.cmdb-inv-grid .lbl-type{flex:0 0 auto;font-size:0.7rem;'
    'padding:1px 6px;border-radius:3px;background:#6c757d;color:#fff;'
    'white-space:nowrap;font-family:monospace;}'
    '</style>'
)


def _render_inventory_grid(_view, _context, model, _name):
    """
    Detail-view inventory rendering — same row styling as labels, but
    a single full-width column so long inventory values (disk serials,
    firmware strings, UUIDs) stay readable without truncation.
    """
    items = model.inventory or {}
    if not items:
        return Markup('<em class="text-muted">No inventory.</em>')
    html = [_INVENTORY_GRID_CSS, '<div class="cmdb-inv-grid">']
    for key in sorted(items.keys(), key=str.lower):
        value = items[key]
        value_str = '' if value is None else str(value)
        type_name = _value_type_name(value)
        html.append(
            '<div class="cmdb-label-row">'
            '<span class="lbl-src">inv</span>'
            f'<span class="lbl-key">{escape(str(key))}</span>'
            f'<span class="lbl-val" title="{escape(value_str)}">'
            f'{escape(value_str)}</span>'
            f'<span class="lbl-type" title="BSON type">{escape(type_name)}</span>'
            '</div>'
        )
    html.append('</div>')
    return Markup(''.join(html))

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


def _render_copy_as_new_form(view, label):
    """
    Render the new-hostname modal for the copy-as-new row action.

    `label` is the user-facing noun ("Host" / "Object") that decides
    only the wording of the not-found flash. The HTML template is the
    same for every view.
    """
    source_id = request.args.get('source_id', '')
    source = Host.objects(id=source_id).first() if source_id else None
    if not source:
        flash(f'{label} not found.', 'error')
        return redirect(url_for('.index_view'))
    return view.render(
        'admin/copy_as_new_form.html',
        source=source,
        default_name=f'{source.hostname}-copy',
    )


def _process_copy_as_new(label):
    """
    Clone the source Host under the new hostname.

    Used by both HostModelView and ObjectModelView. `label` only varies
    the wording of flash messages — the cloning itself is identical
    because Object/Template/Host all live in the same Host collection.
    """
    source_id = request.form.get('source_id', '')
    new_name = (request.form.get('new_hostname') or '').strip()
    if not source_id or not new_name:
        flash('Missing source or new hostname.', 'error')
        return redirect(url_for('.index_view'))
    if Host.objects(hostname=new_name).first():
        flash(f'{label} {new_name!r} already exists.', 'error')
        return redirect(url_for('.index_view'))
    source = Host.objects(id=source_id).first()
    if not source:
        flash(f'{label} not found.', 'error')
        return redirect(url_for('.index_view'))

    clone = Host()
    clone.hostname = new_name
    clone.object_type = source.object_type
    clone.is_object = source.is_object
    clone.no_autodelete = source.no_autodelete
    clone.source_account_name = source.source_account_name or 'cmdb'
    clone.source_account_id = ''
    clone.labels = dict(source.labels or {})
    clone.cmdb_fields = [
        CmdbField(field_name=f.field_name, field_value=f.field_value)
        for f in (source.cmdb_fields or [])
    ]
    clone.cmdb_templates = list(source.cmdb_templates or [])
    clone.cmdb_match = source.cmdb_match
    clone.available = source.available
    clone.last_import_sync = datetime.now()
    clone.last_import_seen = datetime.now()
    clone.save()

    flash(f'Copied to new {label.lower()} {new_name!r}.', 'success')
    return redirect(url_for('.edit_view', id=str(clone.pk)))


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
        'cmdb_fields': _render_cmdb_fields_preview,
        'cmdb_match': _render_cmdb_match_label,
        'object_type': _render_object_type_icon,
    }

    # Detail view uses the rich Key / Value / Type table; the list
    # view stays compact with the badge preview above.
    column_formatters_detail = {
        'log': _render_log_grid,
        'labels': _render_labels_with_origin,
        'inventory': _render_inventory_grid,
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

    def get_export_name(self, _export_type):  # pylint: disable=signature-differs
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

    # Subclasses (e.g. TemplateModelView) set this so on_model_change
    # stamps the right object_type. None = "leave whatever the form had".
    _force_object_type = None

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
        if self._force_object_type is not None:
            model.object_type = self._force_object_type
        new_labels = {x['field_name']: x['field_value'] for x in form.cmdb_fields.data}
        model.update_host(new_labels)
        model.set_inventory_attributes('cmdb')

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('objects')

    # Copy + Timeline row actions. `ObjectModelView` is registered with
    # endpoint="Objects" → Flask-Admin mounts its routes under
    # `admin/objects/`, so we build the row-action URLs to match.
    column_extra_row_actions = [
        LinkRowAction("fa fa-history", app.config['BASE_PREFIX'] + \
                    "admin/objects/timeline?obj_id={row_id}"),
        LinkRowAction("fa fa-copy", app.config['BASE_PREFIX'] + \
                    "admin/objects/copy_as_new_form?source_id={row_id}"),
    ]

    @expose('/timeline')
    def timeline(self):
        """Reuse HostModelView's timeline renderer for CMDB objects."""
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Object not found.', 'error')
            return redirect(url_for('.index_view'))
        changes = list(HostLabelChange.objects(host=host).order_by('-changed_at')[:500])
        return self.render(
            'admin/host_timeline.html', host=host, changes=changes,
        )

    @expose('/copy_as_new_form')
    def copy_as_new_form(self):
        """Render the new-hostname modal for the copy-as-new row action."""
        return _render_copy_as_new_form(self, 'Object')

    @expose('/copy_as_new_process', methods=['POST'])
    def copy_as_new_process(self):
        """Clone the source object under the new hostname."""
        return _process_copy_as_new('Object')


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

    _force_object_type = 'template'

    def get_query(self):
        """
        Limit Objects
        """
        return Host.objects(is_object=True, object_type="template")


class HostModelView(DefaultModelView):  # pylint: disable=too-many-public-methods
    """
    Host Model
    """
    can_create = True
    can_edit = True
    can_export = True
    can_set_page_size = True
    can_view_details = True

    page_size = app.config['HOST_PAGESIZE']

    # Labels already carry per-row badges showing the originating
    # template (see `_render_labels_with_origin`), so the separate
    # "CMDB" block (cmdb_templates + per-template label dumps) would
    # duplicate the same information. Keep `cmdb_templates` out of the
    # detail list.
    column_details_list = [
        'hostname', 'folder', 'no_autodelete', 'available',
        'labels', 'inventory', 'log',
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
        LinkRowAction("fa fa-bug", app.config['BASE_PREFIX'] + \
                    "admin/host/debug?obj_id={row_id}"),
        LinkRowAction("fa fa-history", app.config['BASE_PREFIX'] + \
                    "admin/host/timeline?obj_id={row_id}"),
        LinkRowAction("fa fa-copy", app.config['BASE_PREFIX'] + \
                    "admin/host/copy_as_new_form?source_id={row_id}"),
    ]

    # Adds the top-right search box. Flask-Admin's `init_search` would
    # reject flask-mongoengine's StringField subclass as a non-text
    # column, so we bypass that check in `init_search` below. The actual
    # query is built in `_search()` which searches hostname AND every
    # label value.
    column_searchable_list = ['hostname']

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
        'cmdb_templates': _render_cmdb_template_preview,
        'last_import_seen': _render_datetime,
        'last_import_sync': _render_datetime,
        'create_time': _render_datetime,
        'object_type': _render_object_type_icon,
    }

    # Detail view groups labels by origin (manual vs. each assigned
    # template) so admins can tell at a glance where each value is
    # coming from, and scans cleanly at 50+ labels via the compact
    # two-column grid. Inventory reuses the row style but stays
    # single-column so long values (UUIDs, firmware strings) aren't
    # truncated. Log rows get their own compact scrollable list.
    column_formatters_detail = {
        'log': _render_log_grid,
        'labels': _render_labels_with_origin,
        'inventory': _render_inventory_grid,
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
        # Hosts created/edited here are always of type 'host'. Keep the
        # field in the form as hidden so its value round-trips cleanly,
        # then pin it to 'host' in on_model_change.
        'object_type': HiddenField,
    }

    form_args = {
        'cmdb_templates': {
            'label': 'Assigned Templates',
            'validators': [Optional()],
        },
        'labels_from_template': {
            'label': 'Labels from Templates',
        },
        'cmdb_fields': {
            'label': 'Manual Labels',
        },
    }

    form_rules = [
        rules.FieldSet(
            (
                rules.Field('hostname'),
                rules.Field('available'),
            ),
            "Object",
        ),
        rules.FieldSet(
            (
                rules.HTML('''
<style>
/* Flask-Admin inline-field-list DOM for cmdb_fields (bootstrap4 template):
     <label for="cmdb_fields">Manual Labels</label>
     <div class="inline-field" id="cmdb_fields">
       <div class="inline-field-list">
         <div class="inline-field card card-body bg-light mb-3" id="cmdb_fields-N">
           <legend><small>Manual Labels #N <div class="pull-right">[X]</div></small></legend>
           <div class="clearfix"></div>
           <div class="form-row">
             <div class="form-group"><label>…</label><input class="form-control"></div>
             <div class="form-group"><label>…</label><input class="form-control"></div>
           </div>
         </div>
         ...
       </div>
       <a id="cmdb_fields-button" class="btn btn-primary">Add Manual Labels</a>
     </div>
   Scoped so generic Flask-Admin forms are unaffected. */

/* Outer field label "Manual Labels" — the FieldSet already names the
   section; drop this redundant label. */
label[for="cmdb_fields"] { display: none !important; }

#cmdb_fields .inline-field { position: relative; }

/* Flatten each row card to a plain padded line. */
#cmdb_fields .inline-field.card {
    margin: 0 !important;
    padding: 2px 24px 2px 6px !important;  /* right padding = delete-X area */
    border: none !important;
    box-shadow: none !important;
    background-color: transparent !important;
    border-radius: 0 !important;
}

/* Pin the delete-X to the top-right corner and hide the "#N" caption
   while the X stays interactive. */
#cmdb_fields .inline-field > legend {
    position: absolute !important;
    top: 2px !important;
    right: 2px !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    width: auto !important;
    line-height: 1 !important;
    font-size: 0 !important;  /* kills "Manual Labels #N" caption */
}
#cmdb_fields .inline-field > legend .pull-right {
    font-size: 0.95rem !important;
    float: none !important;
    position: static !important;
}
#cmdb_fields .inline-field > legend small { font-size: 0 !important; }
#cmdb_fields .inline-field > legend small .pull-right { font-size: 0.95rem !important; }
#cmdb_fields .inline-field > .clearfix { display: none !important; }

/* Form-row: horizontal, no wrap, no vertical gap. */
#cmdb_fields .form-row {
    margin: 0 !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    width: 100%;
}
#cmdb_fields .form-group { margin: 0 !important; padding: 0 !important; }
#cmdb_fields .form-group > label { display: none !important; }

/* Field name shrinks to its content width, field value consumes the
   remaining space. `:nth-of-type` instead of `:first/last-child` so the
   selector still binds if Flask-Admin adds a sibling node (error block
   etc.). */
#cmdb_fields .form-row > .form-group:nth-of-type(1) { flex: 0 0 auto; }
#cmdb_fields .form-row > .form-group:nth-of-type(2) {
    flex: 1 1 auto;
    min-width: 0;
    margin-left: 0 !important;
}
#cmdb_fields .form-row > .form-group:nth-of-type(2) input {
    width: 100% !important;
    box-sizing: border-box !important;
}
#cmdb_fields input { padding: 2px 7px !important; height: auto !important; }

/* Two-column grid on wide screens, single column on narrow. */
#cmdb_fields .inline-field-list {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 2px 16px !important;
}
@media (max-width: 992px) {
    #cmdb_fields .inline-field-list { grid-template-columns: 1fr !important; }
}
#cmdb_fields > a.btn { margin-top: 8px; }
</style>
<p class="text-muted small" style="margin: -6px 0 6px 0;">
<i class="fa fa-pencil"></i>
Labels you maintain by hand, plus labels that were seeded from an import
(e.g. CSV). Edit or remove any entry — this list is the single source of
truth for this host. Template-derived labels live in their own section
below and do not appear here.
</p>
'''),
                rules.Field('cmdb_fields'),
            ),
            "Manual Labels (editable)",
        ),
        rules.FieldSet(
            (
                rules.Field('cmdb_templates'),
                rules.Field('labels_from_template'),
            ),
            "Template Labels (read-only)",
        ),
    ]

    form_subdocuments = {
        'cmdb_fields': {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'field_name': {
                            'style': (
                                'background-color: #2EFE9A; '
                                'border-radius: 4px; '
                                'padding: 2px 7px; '
                                'margin-right: 4px; '
                                'font-weight: bold; '
                                'border: 1px solid #1abc9c;'
                            ),
                            'size': 15,
                        },
                        'field_value': {
                            'style': (
                                'background-color: #81DAF5; '
                                'border-radius: 4px; '
                                'padding: 2px 7px; '
                                'font-family: monospace; '
                                'margin-left: 4px; '
                                'border: 1px solid #3498db; '
                                'width: 100%; '
                                'box-sizing: border-box;'
                            ),
                        },
                    },
                    'form_rules': [
                        rules.HTML(
                            '<div class="form-row align-items-center" '
                            'style="margin: 0; flex-wrap: nowrap;">'
                        ),
                        rules.NestedRule(('field_name', 'field_value')),
                        rules.HTML('</div>'),
                    ],
                },
            },
        },
    }

    @expose('/timeline')
    def timeline(self):
        """
        Render a standalone Timeline page for a single host:
        every `HostLabelChange` row, newest first, grouped by day.
        """
        obj_id = request.args.get('obj_id', '').strip()
        host = Host.objects(id=obj_id).first() if obj_id else None
        if not host:
            flash('Host not found.', 'error')
            return redirect(url_for('.index_view'))
        changes = list(HostLabelChange.objects(host=host).order_by('-changed_at')[:500])
        return self.render(
            'admin/host_timeline.html',
            host=host,
            changes=changes,
        )

    @expose('/debug')
    def debug(self):  # pylint: disable=too-many-locals
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

        # Map each rule-group key (as set by the mode-specific debug
        # function) to the Flask-Admin model endpoint. Flask-Admin's
        # default endpoint is `model.__name__.lower()` since none of our
        # add_view() calls override it. Shared across all modes first,
        # then the per-mode specifics win.
        bp = app.config['BASE_PREFIX']
        base_urls = {'CustomAttributes': f"{bp}admin/customattributerule/edit/?id="}
        per_mode = {
            'checkmk_host': {
                'filter':      'checkmkfilterrule',
                'rewrite':     'checkmkrewriteattributerule',
                'actions':     'checkmkrule',
                'Setup Rules': 'checkmkrulemngmt',
            },
            'netbox_device': {
                'rewrite':            'netboxrewriteattributerule',
                'actions':            'netboxcustomattributes',
                'VM Attributes':      'netboxvirtualmachineattributes',
                'Cluster Attributes': 'netboxclusterattributes',
            },
            'ansible_host': {
                'filter':  'ansiblefilterrule',
                'rewrite': 'ansiblerewriteattributesrule',
                'actions': 'ansiblecustomvariablesrule',
            },
            'idoit_host': {
                'rewrite': 'idoitrewriteattributerule',
                'actions': 'idoitcustomattributes',
            },
            'vmware_host': {
                'rewrite': 'vmwarerewriteattributes',
                'actions': 'vmwarecustomattributes',
            },
        }.get(mode, {})
        for group, endpoint in per_mode.items():
            base_urls[group] = f"{bp}admin/{endpoint}/edit/?id="

        new_rules = {}
        for rule_group, rule_data in output_rules.items():
            new_rules.setdefault(rule_group, [])
            for rule in rule_data:
                rule_id = rule.get('id')
                if rule_group in base_urls and rule_id:
                    rule['rule_url'] = f"{base_urls[rule_group]}{rule_id}"
                else:
                    rule['rule_url'] = ''
                new_rules[rule_group].append(rule)

        if "Error" in output:
            output = f"Error: {output['Error']}"

        return self.render('debug_host.html', hostname=hostname, output=output,
                           rules=new_rules, mode=mode)


    # Bulk actions that only make sense when the syncer is in CMDB mode
    # (the host list is the primary place an admin mutates hosts by hand).
    # Filtered out via is_action_allowed() when CMDB_MODE is off so the
    # "With selected..." dropdown stays clean for import-only installs.
    _CMDB_ONLY_ACTIONS = frozenset({
        'copy_as_new', 'bulk_label_edit', 'set_template',
    })

    def __init__(self, model, **kwargs):
        """
        Overwrite based on status
        """

        if not app.config['CMDB_MODE']:
            self.can_edit = False
            self.can_create = False
            self.column_exclude_list.append('cmdb_fields')
            self.column_exclude_list.append('cmdb_templates')
            # The copy-row icon only makes sense when the user is
            # expected to create hosts by hand.
            self.column_extra_row_actions = [
                a for a in (self.column_extra_row_actions or [])
                if 'copy_as_new_form' not in getattr(a, 'url', '')
            ]

        if app.config['LABEL_PREVIEW_DISABLED']:
            self.column_exclude_list.append('labels')

        super().__init__(model, **kwargs)

    def is_action_allowed(self, name):
        if (name in self._CMDB_ONLY_ACTIONS
                and not app.config.get('CMDB_MODE')):
            return False
        return super().is_action_allowed(name)

    def get_export_name(self, _export_type):  # pylint: disable=signature-differs
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

    def init_search(self):
        """
        Bypass Flask-Admin's `type(p) in allowed_search_types` check —
        flask-mongoengine wraps StringField in its own subclass, which
        identity-fails that comparison. We only need the search box to
        appear; `_search()` below drives the actual query.
        """
        for name in self.column_searchable_list or []:
            field = self.model._fields.get(name) if isinstance(name, str) else name
            if field is None:
                raise ValueError(f"Invalid search field: {name!r}")
            self._search_fields.append(field)
        return bool(self._search_fields)

    def _search(self, query, search_term):
        """
        Full-text-ish search across hostname AND any label value.

        Flask-Admin's default search only walks `column_searchable_list`
        (string fields). For a CMDB the most useful search is "find hosts
        whose hostname or ANY label value contains this term", which we
        express as a single Mongo `$or` with `$regex` on hostname and
        `$expr` / `$regexMatch` over the `labels` subdocument values.
        """
        term = (search_term or '').strip()
        if not term:
            return query
        try:
            re.compile(term)
        except re.error:
            # Fall back to a literal match so users typing a stray
            # '[' don't get a 500.
            term = re.escape(term)
        pipeline = {
            '$or': [
                {'hostname': {'$regex': term, '$options': 'i'}},
                {'$expr': {
                    '$anyElementTrue': {
                        '$map': {
                            'input': {'$objectToArray': {
                                '$ifNull': ['$labels', {}],
                            }},
                            'as': 'kv',
                            'in': {
                                '$regexMatch': {
                                    'input': {
                                        '$convert': {
                                            'input': '$$kv.v',
                                            'to': 'string',
                                            'onError': '',
                                            'onNull': '',
                                        },
                                    },
                                    'regex': term,
                                    'options': 'i',
                                },
                            },
                        },
                    },
                }},
            ],
        }
        return query.filter(__raw__=pipeline)

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
        # Merge existing cmdb_fields with labels not yet in the list, then
        # sort alphabetically by name so the form renders in a predictable
        # order. The reorder is in-memory only — on_model_change persists
        # it along with any user edits.
        if obj is not None:
            merged = {
                entry.field_name: (entry.field_value or '')
                for entry in (obj.cmdb_fields or [])
                if getattr(entry, 'field_name', None)
            }
            for label_key, label_value in (obj.labels or {}).items():
                if label_key not in merged:
                    merged[label_key] = (
                        str(label_value) if label_value is not None else ''
                    )
            sorted_fields = []
            for key in sorted(merged.keys(), key=str.lower):
                field = CmdbField()
                field.field_name = key
                field.field_value = merged[key]
                sorted_fields.append(field)
            obj.cmdb_fields = sorted_fields

        form = super().edit_form(obj)
        if obj and hasattr(form, 'labels_from_template'):
            form.labels_from_template.object_data = obj

        if hasattr(form, 'cmdb_templates'):
            form.cmdb_templates.queryset = Host.objects(object_type='template')

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
        # Tag this label mutation as a manual edit so HostLabelChange
        # rows carry the right origin + acting user in the Timeline.
        # pylint: disable=protected-access
        model._label_change_source = 'manual'
        model._label_change_user = getattr(current_user, 'email', None)
        # Hosts created/edited here are always of type 'host' — the form
        # field is hidden so the choice can't be accidentally changed.
        model.object_type = 'host'
        model.cmdb_templates = form.cmdb_templates.data or []
        # Set Extra Fields
        cmdb_fields = app.config['CMDB_MODELS'].get(model.object_type, {})
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

        # Keep the persisted order stable: the edit view sorts entries
        # alphabetically, so on save we preserve that ordering instead of
        # leaving dropped/newly-appended entries out of place.
        model.cmdb_fields = sorted(
            model.cmdb_fields or [],
            key=lambda f: (getattr(f, 'field_name', '') or '').lower(),
        )

    list_template = 'admin/host_list.html'

    def render(self, template, **kwargs):
        """
        Supply the template choice list to the list view so the
        "Set Template" modal can render its <select> inline.
        """
        if template.endswith('host_list.html') or template.endswith('list.html'):
            kwargs.setdefault('set_template_choices', self.get_template_list())
        return super().render(template, **kwargs)

    # `action_set_template` stays as a server-side fallback. The
    # modernized list view intercepts the action client-side and opens
    # a modal instead of redirecting to a separate page — see
    # admin/host_list.html. If JS is disabled the redirect path still
    # works.
    @action('set_template', 'Set Template', None)
    def action_set_template(self, ids):
        """
        Action to set CMDB template
        """
        url = url_for('.set_template_form', ids=','.join(ids))
        return redirect(url)

    @action('bulk_label_edit', 'Bulk Edit Labels', None)
    def action_bulk_label_edit(self, ids):
        """
        Open the bulk label editor (add/remove/rename) for the
        selected hosts. The actual change is applied in bulk_label_process.
        """
        return redirect(url_for('.bulk_label_form', ids=','.join(ids)))

    @action('copy_as_new', 'Copy as new', None)
    def action_copy_as_new(self, ids):
        """
        Clone one Host/Template into a new row. The user is prompted for
        the new hostname in a small modal — labels, cmdb_fields and
        cmdb_templates round-trip, timestamps and sync state are reset
        so the clone doesn't look like a recently-imported object.
        """
        if len(ids) != 1:
            flash('Copy as new requires exactly one selected row.', 'error')
            return redirect(url_for('.index_view'))
        return redirect(url_for('.copy_as_new_form', source_id=ids[0]))

    @expose('/copy_as_new_form')
    def copy_as_new_form(self):
        """Render the new-hostname modal for the copy-as-new action."""
        return _render_copy_as_new_form(self, 'Host')

    @expose('/copy_as_new_process', methods=['POST'])
    def copy_as_new_process(self):
        """Clone the source Host under the new hostname."""
        return _process_copy_as_new('Host')

    @expose('/bulk_label_form')
    def bulk_label_form(self):
        """Render the bulk label editor for the ids passed in the URL."""
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',') if i]
        return render_template('admin/bulk_label_form.html', ids=ids)

    @expose('/bulk_label_process', methods=['POST'])
    def bulk_label_process(self):
        """
        Apply an add / remove / rename label operation to every host in
        `host_ids`. Uses `update_host` so existing side-effects (log entry,
        last_import_sync bump, cache invalidation) still fire per host.
        """
        host_ids = [x for x in request.form.get('host_ids', '').split(',') if x]
        mode = request.form.get('mode', '')
        key = (request.form.get('label_key') or '').strip()
        value = (request.form.get('label_value') or '').strip()
        new_key = (request.form.get('new_key') or '').strip()

        if mode not in ('add', 'remove', 'rename') or not key:
            flash('Invalid bulk label request', 'error')
            return redirect(url_for('.index_view'))
        if mode == 'rename' and not new_key:
            flash('Rename needs a new key', 'error')
            return redirect(url_for('.index_view'))

        changed = 0
        skipped = 0
        user_email = getattr(current_user, 'email', None)
        for host_id in host_ids:
            host = Host.objects(id=host_id).first()
            if not host:
                continue
            labels = dict(host.labels or {})
            before = dict(labels)
            if mode == 'add':
                labels[key] = value
            elif mode == 'remove':
                labels.pop(key, None)
            elif mode == 'rename':
                if key in labels:
                    labels[new_key] = labels.pop(key)
                else:
                    skipped += 1
                    continue
            if labels != before:
                # Tag the change so HostLabelChange rows show "manual"
                # + the acting user in the Timeline, not "import".
                # pylint: disable=protected-access
                host._label_change_source = 'manual'
                host._label_change_user = user_email
                host.update_host(labels)
                host.save()
                changed += 1

        flash(
            f'Bulk label {mode}: updated {changed} host(s)'
            + (f', {skipped} skipped (key not present)' if skipped else ''),
            'success' if changed else 'warning',
        )
        return redirect(url_for('.index_view'))


    @expose('/set_template_form')
    def set_template_form(self):
        """
        Custom form for template selection
        """
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',')]
        templates = self.get_template_list()

        return render_template('admin/set_template_form.html', ids=ids, templates=templates)

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
