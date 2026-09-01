"""
Inventory rendering for the Host detail view.

Split off from `host_renderers` because the inventory of a host that is
inventorized from several sources is the largest thing the detail view
draws: it groups the entries by the key their account wrote them under
and puts each source behind a tab, so a host with hundreds of entries
stays readable.
"""
from markupsafe import Markup, escape


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


# The separator update_inventory() puts between the key an account
# inventorized under and the field of the record, e.g.
# ``snow_cmdb_ci_network_adapter__0_name``
_INVENTORY_SOURCE_SEP = '__'

# Entries written without that separator — a plugin storing a single
# attribute, a hand-edited key — all end up in one tab of their own
_INVENTORY_NO_SOURCE = 'other'

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
    '.cmdb-inv-tabs{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 6px 0;'
    'padding:0 0 4px 0;list-style:none;'
    'border-bottom:1px solid var(--surface-border,#dee2e6);}'
    '.cmdb-inv-tabs button{border:1px solid transparent;background:none;'
    'padding:3px 10px;border-radius:3px;font-size:0.82rem;cursor:pointer;'
    'color:var(--surface-muted,#6c757d);font-family:inherit;}'
    '.cmdb-inv-tabs button:hover{color:#1abc9c;'
    'border-color:var(--surface-border,#dee2e6);}'
    '.cmdb-inv-tabs button.active{color:#1abc9c;font-weight:600;'
    'background:var(--surface-subtle,#f1f3f5);'
    'border-color:var(--surface-border,#dee2e6);}'
    '.cmdb-inv-tabs .tab-count{font-size:0.72rem;opacity:0.7;'
    'margin-left:4px;font-variant-numeric:tabular-nums;}'
    '.cmdb-inv-grid .cmdb-label-row[hidden]{display:none;}'
    '</style>'
)

# Switching a tab only flips the hidden flag of the rows — every entry
# is already on the page, so there is nothing to fetch and no state to
# keep. Written once per grid, scoped to that grid's own id.
_INVENTORY_TABS_JS = (
    '<script>(function(){'
    'var box=document.getElementById("%(grid_id)s");'
    'if(!box){return;}'
    'box.querySelector(".cmdb-inv-tabs").addEventListener("click",function(ev){'
    'var btn=ev.target.closest("button");'
    'if(!btn){return;}'
    'var want=btn.getAttribute("data-source");'
    'box.querySelectorAll(".cmdb-inv-tabs button").forEach(function(other){'
    'other.classList.toggle("active",other===btn);});'
    'box.querySelectorAll(".cmdb-label-row").forEach(function(row){'
    'row.hidden=(want!=="*"&&row.getAttribute("data-source")!==want);});'
    '});}());</script>'
)


def _inventory_by_source(items):
    """
    The inventory entries grouped under the key the account inventorized
    them with, as {source: [(key, value)]} — sources sorted, and the
    entries inside a source sorted the way the flat list was.

    The full key stays on the entry: it is what a rule matches on, so
    shortening it on screen would hide what has to be typed.
    """
    grouped = {}
    for key in sorted(items.keys(), key=str.lower):
        name = str(key)
        source = (name.split(_INVENTORY_SOURCE_SEP, 1)[0]
                  if _INVENTORY_SOURCE_SEP in name else _INVENTORY_NO_SOURCE)
        grouped.setdefault(source, []).append((name, items[key]))
    return dict(sorted(grouped.items()))


def _render_inventory_grid(_view, _context, model, _name):
    """
    Detail-view inventory rendering — same row styling as labels, but
    a single full-width column so long inventory values (disk serials,
    firmware strings, UUIDs) stay readable without truncation.

    A host inventorized from several sources carries hundreds of
    entries, so each source gets a tab and only one of them is shown at
    a time. A single source needs no tab bar and keeps the plain list.
    """
    items = model.inventory or {}
    if not items:
        return Markup('<em class="text-muted">No inventory.</em>')

    by_source = _inventory_by_source(items)
    grid_id = f'cmdb-inv-{model.pk}'
    html = [_INVENTORY_GRID_CSS, f'<div id="{escape(grid_id)}">']

    tabbed = len(by_source) > 1
    if tabbed:
        html.append('<ul class="cmdb-inv-tabs">')
        html.append(f'<li><button type="button" class="active" data-source="*">All'
                    f'<span class="tab-count">{len(items)}</span></button></li>')
        for source, entries in by_source.items():
            html.append(
                f'<li><button type="button" data-source="{escape(source)}">'
                f'{escape(source)}'
                f'<span class="tab-count">{len(entries)}</span></button></li>')
        html.append('</ul>')

    html.append('<div class="cmdb-inv-grid">')
    for source, entries in by_source.items():
        for key, value in entries:
            value_str = '' if value is None else str(value)
            type_name = _value_type_name(value)
            html.append(
                f'<div class="cmdb-label-row" data-source="{escape(source)}">'
                f'<span class="lbl-src">{escape(source if tabbed else "inv")}</span>'
                f'<span class="lbl-key">{escape(key)}</span>'
                f'<span class="lbl-val" title="{escape(value_str)}">'
                f'{escape(value_str)}</span>'
                f'<span class="lbl-type" title="BSON type">{escape(type_name)}</span>'
                '</div>'
            )
    html.append('</div></div>')
    if tabbed:
        html.append(_INVENTORY_TABS_JS % {'grid_id': grid_id})
    return Markup(''.join(html))
