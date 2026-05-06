"""
Column formatters / renderers for the Host model views.

Extracted from `application.views.host` so the main module can stop
hosting ~660 lines of HTML-rendering helpers. Every function in here
matches Flask-Admin's `column_formatters` callable signature
`(view, context, model, name) -> Markup` (or the export-flavour
`(view, context, model, prop) -> str`).

Imports stay narrow on purpose: these helpers should not pull in any
of the Host-action machinery (copy_as_new, bulk-label processors).
"""
import re
from datetime import datetime

from flask import url_for
from markupsafe import Markup, escape

from application import app
from application.modules.log.models import LogEntry
from application.views.host_filters import FilterCmdbTemplate


# Icon mappings for object types
OBJECT_TYPE_ICONS = {
    'auto': 'fa fa-magic',
    'application': 'fa fa-code',
    'service': 'fa fa-cogs',
    'location': 'fa fa-map-marker',
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

_LIFECYCLE_BADGES = {
    'planned':        ('badge-secondary', 'fa fa-clock'),
    'staged':         ('badge-info',      'fa fa-flask'),
    'active':         ('badge-success',   'fa fa-check-circle'),
    'decommissioned': ('badge-warning',   'fa fa-power-off'),
    'archived':       ('badge-dark',      'fa fa-archive'),
}


def _render_lifecycle_state(_view, _context, model, _name):
    """
    Bootstrap badge for the host lifecycle state. Default 'active'
    when the field is empty so legacy rows render usefully. Adds a
    secondary "Stale" badge when the `sys mark_stale` cronjob has
    flagged the host as not seen recently.
    """
    state = getattr(model, 'lifecycle_state', None) or 'active'
    badge_class, icon_class = _LIFECYCLE_BADGES.get(
        state, ('badge-light', 'fa fa-question')
    )
    label = state.replace('_', ' ').title()
    html = (
        f'<span class="badge {escape(badge_class)}">'
        f'<i class="{escape(icon_class)}" style="margin-right: 4px;"></i>'
        f'{escape(label)}</span>'
    )
    if getattr(model, 'is_stale', False):
        stale_since = getattr(model, 'stale_since', None)
        title = (f"Stale since {stale_since:%Y-%m-%d}"
                 if stale_since else "No fresh import for too long")
        html += (
            f' <span class="badge badge-warning" title="{escape(title)}">'
            f'<i class="fa fa-hourglass-end" style="margin-right: 4px;"></i>'
            f'Stale</span>'
        )
    return Markup(html)


def _render_relations(_view, _context, model, _name):  # pylint: disable=too-many-locals
    """
    Detail-view rendering for `Host.relations`. Lists outgoing edges as
    a small key/value grid, then appends inbound edges grouped by type
    so the Impact Chain (incoming `depends_on`) is visible at a glance.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import RELATION_TYPES, RELATION_INVERSE_LABEL
    relations = model.relations or []
    type_label = dict(RELATION_TYPES)

    rows = []
    for rel in relations:
        target = rel.target_host
        if not target:
            continue
        href = url_for('host.details_view', id=str(target.pk))
        label = type_label.get(rel.type, rel.type)
        rows.append(
            f'<tr><td><span class="badge badge-secondary">{escape(label)}</span></td>'
            f'<td><a href="{escape(href)}">{escape(target.hostname)}</a></td>'
            f'<td><small class="text-muted">{escape(rel.source or "")}</small></td>'
            f'</tr>'
        )

    inbound_by_type = {}
    pk = getattr(model, 'pk', None)
    if pk is not None:
        from application.models.host import Host
        inbound = Host.objects(__raw__={'relations.target_host': pk}).only(
            'hostname', 'relations'
        )
        for src in inbound:
            for rel in (src.relations or []):
                if rel.target_host and rel.target_host.pk == pk:
                    inbound_by_type.setdefault(rel.type, []).append(src)

    inbound_rows = []
    for rtype, sources in inbound_by_type.items():
        inv_label = RELATION_INVERSE_LABEL.get(rtype, rtype)
        for src in sources:
            href = url_for('host.details_view', id=str(src.pk))
            inbound_rows.append(
                f'<tr><td><span class="badge badge-info">{escape(inv_label)}</span></td>'
                f'<td><a href="{escape(href)}">{escape(src.hostname)}</a></td>'
                f'<td></td></tr>'
            )

    if not rows and not inbound_rows:
        return Markup('<span class="text-muted">No relations</span>')

    html = ['<table class="table table-sm table-borderless mb-0">'
            '<thead><tr><th style="width:160px">Type</th>'
            '<th>Host</th><th>Source</th></tr></thead><tbody>']
    if rows:
        html.append('<tr><td colspan="3" class="bg-light"><strong>'
                    'Outgoing</strong></td></tr>')
        html.extend(rows)
    if inbound_rows:
        html.append('<tr><td colspan="3" class="bg-light"><strong>'
                    'Inbound (Impact Chain)</strong></td></tr>')
        html.extend(inbound_rows)
    html.append('</tbody></table>')
    return Markup(''.join(html))


def _render_relations_preview(_view, _context, model, _name):
    """List view: just show count of outgoing/inbound edges."""
    out = len(model.relations or [])
    inbound = 0
    pk = getattr(model, 'pk', None)
    if pk is not None:
        # pylint: disable=import-outside-toplevel
        from application.models.host import Host
        inbound = Host.objects(__raw__={'relations.target_host': pk}).count()
    if not out and not inbound:
        return Markup('<span class="text-muted">—</span>')
    return Markup(
        f'<span title="outgoing">→ {out}</span>'
        f' <span title="inbound" class="text-muted">← {inbound}</span>'
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
    # pylint: disable=too-many-locals
    """
    Compact read-only detail rendering of a host's labels grouped by
    origin. In CMDB mode each row carries a small badge (``manual`` or
    the template hostname) so the admin can tell where a label came
    from; without CMDB mode there are no templates and the prefix is
    just visual noise, so it's dropped. Type badge stays in both modes
    (admins still want to tell a string `"True"` from a BSON bool).
    """
    cmdb_mode = bool(app.config.get('CMDB_MODE'))
    manual = model.labels or {}
    templates = []
    if cmdb_mode:
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
        if not cmdb_mode:
            src_badge = ''
        elif origin == 'manual':
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


def _cmdb_template_filter_url(view, tmpl):
    """
    Build a host-list URL pre-filtered to the given template. Looks up
    `FilterCmdbTemplate`'s position in `view._filters` so the link
    survives reordering of `column_filters`. Returns '' if the filter
    isn't wired into this view (e.g. ObjectModelView).
    """
    filters = getattr(view, '_filters', None) or []
    for idx, flt in enumerate(filters):
        if isinstance(flt, FilterCmdbTemplate):
            try:
                return url_for(
                    f'{view.endpoint}.index_view',
                    **{f'flt0_{idx}': str(tmpl.id)},
                )
            except Exception:  # pylint: disable=broad-exception-caught
                return ''
    return ''


def _render_cmdb_template_preview(view, _context, model, _name):
    """
    Compact badge preview of assigned CMDB templates for the list
    view — just the template hostnames, same badge style as the
    label preview. Each badge links to the template's edit page; a
    small filter icon next to it filters the host list to all hosts
    sharing that template (the "group by template" shortcut).
    """
    if not model.cmdb_templates:
        return Markup("")
    html = f'<div style="{_LABEL_WRAPPER_STYLE}">'
    for tmpl in model.cmdb_templates:
        name = escape(tmpl.hostname)
        badge = (
            f'<span class="badge badge-dark" '
            f'style="{_LABEL_BADGE_STYLE}" '
            f'title="{name}">'
            f'<i class="fa fa-file"></i> {name}</span>'
        )
        href = _template_edit_url(tmpl)
        if href:
            badge_html = (
                f'<a href="{escape(href)}" '
                f'style="text-decoration: none;">{badge}</a>'
            )
        else:
            badge_html = badge

        filter_href = _cmdb_template_filter_url(view, tmpl)
        if filter_href:
            filter_icon = (
                f'<a href="{escape(filter_href)}" '
                f'style="text-decoration: none; color: #6c757d; '
                f'margin-left: 4px;" '
                f'title="Show all hosts using this template">'
                f'<i class="fa fa-filter"></i></a>'
            )
        else:
            filter_icon = ''

        html += (
            f'<span style="display: inline-block; white-space: nowrap; '
            f'margin-right: 6px;">{badge_html}{filter_icon}</span>'
        )
    html += '</div>'
    return Markup(html)

def _render_cmdb_match_label(_view, _context, model, _name):
    """
    Render CMDB Match as badge label
    """
    if not model.cmdb_match:
        return Markup('<span class="text-muted">N/A</span>')
    return Markup(f'<span class="badge badge-primary">{escape(model.cmdb_match)}</span>')


def get_rule_json(_view, _context, model, _name):
    """
    Export Given Rulesets
    """
    return model.to_json()

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
    `input_monitoring:True` does or doesn't match a filter. ``None``
    becomes ``empty`` so the badge stays readable when an importer
    drops a label with no value.
    """
    if value is None:
        return 'empty'
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
