"""
Lookup Table View
"""
from markupsafe import Markup, escape
from flask import flash
from flask_admin.form import rules
from flask_login import current_user
from wtforms import StringField, TextAreaField

from application.docu_links import docu_links
from application.helpers.lookup_table import clear_cache, parse_lookup_table
from application.helpers.sates import add_changes
from application.modules.rule.views import invalidate_host_rule_caches
from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


def _render_table_summary(_view, _context, model, _name):
    """List column: the columns of a table and how many keys it has."""
    columns, table, errors = parse_lookup_table(model.entries)
    if errors:
        return Markup('<span class="text-danger">invalid</span>')
    if not columns:
        return Markup('<em>empty</em>')
    return Markup(f'{len(table)} keys, columns: '
                  f'<code>{escape(", ".join(columns))}</code>')


_HELP = Markup(
    '<div class="small" style="margin-bottom: 8px;"><ul style="padding-left: 18px;">'
    '<li><b>First line = column names</b>, every further line one entry. '
    'The first column is the key, the other columns are values.</li>'
    '<li>Separator (tab from a spreadsheet, <code>;</code>, <code>,</code> or '
    '<code>|</code>) is detected from the first line.</li>'
    "<li>Use it in any Jinja field: <code>{{ lookup('table_name', location) }}"
    "</code> gives the second column of the line whose key is the value of "
    "<code>location</code>, <code>{{ lookup('table_name', location, "
    "'datacenter') }}</code> the column <code>datacenter</code>, "
    "<code>{{ lookup('table_name', location, default='unknown') }}</code> "
    "a fallback.</li>"
    '</ul></div>')


class LookupTableView(DefaultModelView):
    """
    Lookup Tables
    """
    column_list = ('name', 'documentation', 'entries')
    column_sortable_list = ('name',)
    column_filters = ('name',)
    column_formatters = {
        'entries': _render_table_summary,
    }
    column_labels = {
        'entries': 'Table',
    }

    form_overrides = {
        'name': StringField,
        'entries': TextAreaField,
    }

    form_args = {
        'entries': {'label': 'Table'},
    }

    form_widget_args = {
        'entries': {
            'rows': 20,
            'style': 'font-family: monospace; white-space: pre;',
            'placeholder': 'location;datacenter\nsite-a;DC1\nsite-b;DC2',
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["lookup_tables"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Main Options',
                    'Name the table the way templates refer to it.',
                    [rules.Field('name'),
                     rules.Field('documentation')]),
            section('2', 'out', 'Table',
                    'Key in the first column, values in the others.',
                    [rules.HTML(_HELP),
                     rules.Field('entries')]),
        ),
    ]

    def validate_form(self, form):
        """
        Refuse a table that cannot be read: every lookup in it would
        silently fall back to its default.
        """
        if not super().validate_form(form):
            return False
        entries = getattr(form, 'entries', None)
        if entries is None:
            # Not the table form (e.g. the delete form).
            return True
        _columns, _table, errors = parse_lookup_table(entries.data)
        for message in errors:
            flash(f"Table: {message}", 'danger')
        return not errors

    def on_model_change(self, form, model, is_created):
        """
        Host attributes computed with the old table are cached on the
        hosts: drop them, as a rule change does.
        """
        super().on_model_change(form, model, is_created)
        add_changes()
        clear_cache()
        invalidate_host_rule_caches()

    def on_model_delete(self, model):
        """
        Drop the caches, the lookups of the table now give their default.
        """
        add_changes()
        clear_cache()
        invalidate_host_rule_caches()
        return super().on_model_delete(model)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
