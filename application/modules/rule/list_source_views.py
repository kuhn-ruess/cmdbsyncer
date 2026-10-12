"""
Form side of a rule with a list source (see ``list_source.py``)

A rule view offers the list by mixing in ``ListSourceViewMixin``. For a
model with the list fields (see ``list_source_fields``) the view then has
the Rule source switch, the List field with its live preview, the check on
save and the preview endpoint; for a model without them it stays a plain
rule view, so one view class can serve both. What is rule type specific
(what a row creates, the outcome fields rendered per row, extra help) is
set as class attributes; the form is built from them by
``list_source_rule_form``.
"""
from markupsafe import Markup
from flask import flash, request
from flask_admin.base import expose
from flask_admin.form import rules
from wtforms import TextAreaField

from application.helpers.syncer_jinja import global_names
from application.modules.rule.list_source import (
    RULE_SOURCE_CHOICES,
    RULE_SOURCE_HOSTS,
    RULE_SOURCE_LIST,
    check_list_rule,
    outcome_templates,
    rule_uses_list,
)
from application.views._form_sections import modern_form, section

# Main card of a rule form, as RuleModelView has it.
RULE_MAIN_FIELDS = (
    rules.Field('name'),
    rules.Field('documentation'),
    rules.HTML('<div class="form-check form-check-inline">'),
    rules.NestedRule(('enabled', 'last_match')),
    rules.HTML('</div>'),
    rules.Field('sort_field'),
)

# Create and edit page of a rule with a list source.
_LIST_PAGES = ('admin/model/list_source_create.html',
               'admin/model/list_source_edit.html')

# Names of the separators in the preview.
_DELIMITER_NAMES = {'\t': 'tab', ';': 'semicolon', ',': 'comma', '|': 'pipe'}


def _per_row(creates, per_outcome):
    """What a row turns into, for the help and the card description."""
    if per_outcome:
        return f'one {creates} per row and per outcome'
    return f'one {creates} per row, made of all outcomes'


def list_source_help(creates, items, per_outcome=True):
    """
    The help shown above the List field: how columns become variables,
    what a row creates (``creates`` names one of it, e.g. 'Checkmk rule';
    ``per_outcome``: every outcome of a row creates one, else all outcomes
    of a row make up one), the rule type specific ``items`` (HTML of one
    list entry each) and how the separator is found.
    """
    entries = [
        '<b>First line = column names.</b> Each column becomes a Jinja '
        'variable for the outcome fields below: lower case, every space or '
        'special character becomes <code>_</code>, so <code>Service Level'
        '</code> is <code>{{ service_level }}</code>. The whole row is '
        '<code>{{ row }}</code>, its 0-based number <code>{{ row_idx }}'
        '</code>. The variables of your list are listed below the field as '
        'you paste.',
        f'<b>The list replaces the hosts:</b> {_per_row(creates, per_outcome)}.',
        *items,
        'Separator (tab from a spreadsheet, <code>;</code>, <code>,</code> or '
        '<code>|</code>) is detected from the first line.',
    ]
    return Markup(
        '<div id="list-source-help" class="small" style="margin-bottom: 8px;">'
        '<ul style="padding-left: 18px; margin-bottom: 4px;">'
        + ''.join(f'<li>{entry}</li>' for entry in entries)
        + '</ul></div>')


def list_source_rule_form(main_fields, creates, help_items, outcome,
                          per_outcome=True):
    """
    ``form_rules`` of a rule with a list source: the three step cards of
    every rule form, with the Rule source switch below the main fields and
    a Pasted List card next to the Conditions. Only one of the two step 2
    cards is shown, depending on the rule source (see
    ``_list_source_preview.html``).

    ``creates`` names what one row and outcome create (``per_outcome``,
    else what one row creates of all its outcomes), ``help_items`` add
    rule type specific entries to the help (see ``list_source_help``),
    ``outcome`` is the ``(title, description)`` of the outcomes card.
    """
    outcome_title, outcome_desc = outcome
    return modern_form(
        section('1', 'main', 'Main Options',
                'Name, description, activation and where the rule gets its '
                'input from.',
                [*main_fields, rules.Field('rule_source')]),
        section('2', 'cond', 'Pasted List',
                f'{_per_row(creates, per_outcome).capitalize()}. Host '
                'conditions do not apply.',
                [rules.HTML(list_source_help(creates, help_items, per_outcome)),
                 rules.Field('list_source'),
                 rules.HTML('<div id="list-source-preview"></div>')]),
        section('2', 'cond', 'Conditions',
                'When does this rule apply? '
                'Match hostname or any host attribute.',
                [rules.Field('condition_typ'),
                 rules.Field('conditions')]),
        section('3', 'out', outcome_title,
                f'{outcome_desc} With a pasted list, click a column variable '
                'above to insert it into the field you were editing.',
                [rules.Field('outcomes')]),
    )


class ListSourceViewMixin:
    """
    Rule source switch, List field, live preview and the check on save for
    a rule view. Mix in before the view's base class.
    """
    # What one row and outcome create, e.g. 'i-doit object'. When set, the
    # form is built by ``list_source_rule_form`` from the attributes below;
    # otherwise the view brings its own ``form_rules``.
    list_source_creates = None
    list_source_main_fields = RULE_MAIN_FIELDS
    list_source_help_items = ()
    list_source_outcome = ('Outcomes', 'What the rule creates.')
    # Every outcome of a row creates one object (else all outcomes of a
    # row make up one object, as they would for a host).
    list_source_per_outcome = False
    # (field, label) of the outcome fields rendered per row: the save and
    # the preview warn when one of them reads a variable that is no column.
    list_source_template_fields = ()
    # Variables every row knows besides its columns, e.g. the account.
    list_source_known_names = ()
    list_source_placeholder = 'hostname;value\nsrv01;gold\nsrv02;silver'

    def __init__(self, model, **kwargs):
        if 'list_source' not in model._fields:  # pylint: disable=protected-access
            # A rule type of this view without a list.
            super().__init__(model, **kwargs)
            return
        # The list pages extend the view's own pages, see render.
        self.create_template, self.edit_template = _LIST_PAGES
        if self.list_source_creates:
            self.form_rules = list_source_rule_form(
                main_fields=list(self.list_source_main_fields),
                creates=self.list_source_creates,
                help_items=self.list_source_help_items,
                outcome=self.list_source_outcome,
                per_outcome=self.list_source_per_outcome,
            )
        self.form_overrides = {**(self.form_overrides or {}),
                               'list_source': TextAreaField}
        self.form_args = {**(getattr(self, 'form_args', None) or {}),
                          'rule_source': {
            'label': 'Rule source',
            'choices': RULE_SOURCE_CHOICES,
            'default': RULE_SOURCE_HOSTS,
            'description': (
                "Per host: the outcomes are rendered for every host matching "
                "the conditions, with the host's attributes. From a pasted "
                "list: the outcomes are rendered once per row of a list you "
                "paste, with its columns; host conditions and Static Rule do "
                "not apply."
            ),
        }}
        self.form_widget_args = {
            **(getattr(self, 'form_widget_args', None) or {}),
            'list_source': {
                'rows': 8,
                'style': 'font-family: monospace; white-space: pre;',
                'placeholder': self.list_source_placeholder,
            },
        }
        # A pasted list is no table cell.
        self.column_exclude_list = [*(self.column_exclude_list or []),
                                    'list_source']
        super().__init__(model, **kwargs)

    def render(self, template, **kwargs):
        """
        Tell a list page which page of the view it extends: the create or
        edit page the view class has.
        """
        if template in _LIST_PAGES:
            kwargs['list_source_base'] = (type(self).create_template
                                          if template == _LIST_PAGES[0]
                                          else type(self).edit_template)
        return super().render(template, **kwargs)

    def _check_list_rule(self, data):
        """
        ``check_list_rule`` on submitted form data: the rule source, the
        list and every ``outcomes-N-<field>`` template.
        """
        return check_list_rule(
            data.get('rule_source'), data.get('list_source'),
            outcome_templates(data, self.list_source_template_fields),
            known_names=global_names() | set(self.list_source_known_names))

    def validate_form(self, form):
        """
        Refuse a list rule the export could not use: an unreadable list
        creates nothing at all, and a rule that created something before
        would remove it. Variables that are no column only warn.
        """
        if not super().validate_form(form):
            return False
        data = {field.name: field.data for field in form
                if field.name in ('rule_source', 'list_source')}
        if not data:
            # Not the rule form (e.g. the delete or list edit form).
            return True
        for entry in getattr(getattr(form, 'outcomes', None), 'entries', None) or []:
            for field in getattr(entry, 'form', None) or []:
                data[field.name] = field.data
        _parsed, errors, warnings = self._check_list_rule(data)
        for message in warnings:
            flash(message, 'warning')
        for message in errors:
            flash(message, 'danger')
        return not errors

    @expose('/_list_source_preview', methods=['POST'])
    def list_source_preview(self):
        """
        Parse a pasted list the way the export will and answer with the
        column variables, the first rows, every problem and the outcome
        templates reading a variable that is no column. Feeds the preview
        under the List field while the rule is being edited.
        """
        data = request.form.to_dict()
        data['rule_source'] = RULE_SOURCE_LIST
        parsed, errors, warnings = self._check_list_rule(data)
        return {
            'columns': parsed.columns,
            'rows': parsed.rows[:20],
            'row_count': len(parsed.rows),
            'delimiter': _DELIMITER_NAMES.get(parsed.delimiter, ''),
            'errors': errors,
            'warnings': warnings,
        }

    def on_form_prefill(self, form, id):  # pylint: disable=redefined-builtin
        """
        A rule saved before the rule source switch existed shows the mode
        it is exported in: from the list when one is filled in.
        """
        super().on_form_prefill(form, id)
        if hasattr(form, 'rule_source') and not form.rule_source.data:
            form.rule_source.data = (
                RULE_SOURCE_LIST if rule_uses_list(None, form.list_source.data)
                else RULE_SOURCE_HOSTS)
