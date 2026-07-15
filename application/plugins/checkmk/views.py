"""
Checkmk Rule Views
"""
# pylint: disable=too-many-lines
# pylint: disable=duplicate-code
import json
from markupsafe import Markup, escape

from pygments import highlight
from pygments.formatters import HtmlFormatter  # pylint: disable=no-name-in-module
from pygments.lexers import DjangoLexer  # pylint: disable=no-name-in-module

from wtforms import HiddenField, StringField, PasswordField, SelectMultipleField, SelectField
from wtforms.validators import ValidationError
from flask_admin import BaseView
from flask_admin.form import rules
from flask_admin.actions import action
from flask_admin.base import expose
from flask_admin.contrib.mongoengine.filters import (
    BaseMongoEngineFilter,
    BooleanEqualFilter,
    FilterLike,
)
from flask import redirect, url_for, request, render_template, flash, Response

from flask_login import current_user
from application import app
from application.views.default import DefaultModelView
from application.models.account import Account, CustomEntry
from application.docu_links import docu_links

from application.modules.rule.views import (
    RuleModelView,
    form_subdocuments_template,
    _render_full_conditions,
    get_rule_json,
    _render_jinja,
    _modern_rule_form,
)
from application.views._form_sections import modern_form, section
from .models import (
    action_outcome_types,
    CheckmkSite,
    CheckmkSettings,
    CheckmkRuleMngmt,
    CheckmkRuleProject,
    CheckmkDCDRule,
)


def _project_choices():
    """Blank + every existing rule project — feeds the rule's project picker."""
    names = [p.name for p in CheckmkRuleProject.objects.order_by('name')]
    return [('', '— none (global) —'), *((n, n) for n in names)]


class ProjectSelectField(SelectField):
    """SelectField populated from the CheckmkRuleProject collection."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', _project_choices)
        # Keep editing a rule whose project was renamed/removed working.
        kwargs.setdefault('validate_choice', False)
        super().__init__(*args, **kwargs)


def _cmk_account_choices():
    """Every enabled Checkmk (cmkv2) account — feeds the project account filter."""
    return [(a.name, a.name)
            for a in Account.objects(enabled=True, type='cmkv2').order_by('name')]


class CheckmkAccountsMultiSelectField(SelectMultipleField):
    """Multi-select of Checkmk accounts, stored as a list of account names."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', _cmk_account_choices)
        # Tolerate a saved name whose account was since disabled/removed.
        kwargs.setdefault('validate_choice', False)
        super().__init__(*args, **kwargs)


div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")

main_open = rules.HTML('<div class="card">'\
        '<h5 class="card-header">Main Options</h5>'\
        '<div class="card-body">')
main_close = rules.HTML("</div></div><br>")

checkmk_open = rules.HTML('<div class="card">'\
        '<h5 class="card-header">Checkmk Options</h5>'\
        '<div class="card-body">')
checkmkl_close = rules.HTML("</div></div>")

addional_open = rules.HTML('<div class="card">'\
    '<h5 class="card-header">Addional Options</h5>'\
        '<div class="card-body">')
addional_close = rules.HTML("</div></div>")

def _render_dw_rule(_view, _context, model, _name):
    """
    Render Downtime Rule
    """
    html = ""
    for idx, entry in enumerate(model.outcomes):
        idx += 1
        data = [
            ("Every", entry['every']),
            ("Day", entry['start_day']),
            ("Hour", entry['start_time_h']),
            ("Min", entry['start_time_m']),
        ]
        out_lines = ""
        for what, value in data:
            if not value:
                continue
            highlighted = \
                    highlight(value, DjangoLexer(),
                              HtmlFormatter(sytle='colorfull'))
            out_lines += f"{what}: {highlighted}"

        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">Downtime {idx}</h6>
                </p>
                  {out_lines}
              </div>
            </div>
            '''

    return Markup(html)


def _render_dcd_rule(_view, _context, model, _name):
    """
    Render Downtime Rule
    """

    html = ""
    for entry in model.outcomes:
        dcd_id = \
                highlight(str(entry['dcd_id']), DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        title  = \
                highlight(str(entry['title']), DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">{dcd_id}</h6>
                 {title}
                </p>
              </div>
            </div>
            '''
    return Markup(html)

def _render_bi_rule(_view, _context, model, _name):
    """
    Render BI Rule
    """
    html = '''
        <div class="card">
            <div class="card-body">
            <p class="card-text">
            <ul class="list-group">
    '''
    for idx, entry in enumerate(model.outcomes):
        html += f"<li class='list-group-item'>{idx}: {escape(entry['description'])}</li>"
    html += '''
            </ul>
            </p>
            </div>
        </div>
    '''
    return Markup(html)

def _render_checkmk_outcome(_view, _context, model, _name):
    """
    Render Checkmk outcomes
    """
    html = ""
    for entry in model.outcomes:
        name = escape(dict(action_outcome_types)[entry.action].split('_',1)[0])
        highlighted_param = ""
        if entry.action_param:
            highlighted_param = highlight(
                str(entry.action_param),
                DjangoLexer(),
                HtmlFormatter(sytle='colorfull')
            )
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">{name}</h6>
                </p>
                <p class="card-text">
                {highlighted_param}
                </p>
              </div>
            </div>
            '''

    return Markup(html)

def _render_group_outcome(_view, _context, model, _name):
    """
    Render Group Outcome
    """
    entry = model.outcome
    html = f'''
        <div class="card">
            <div class="card-body">
            <p class="card-text">
                <h6 class="card-subtitle mb-2 text-muted">{escape(entry.group_name)}</h6>
            </p>
            <p class="card-text">
            <ul>
            <li>Foreach: {escape(entry.foreach_type)}</li>
            <li>Value: {escape(entry.foreach)}</li>
            <li>Jinja Name Rewrite: {escape(entry.rewrite)}</li>
            <li>Jinja Title Rewrite: {escape(entry.rewrite_title)}</li>
            </ul>
            </p>
            </div>
        </div>
    '''
    return Markup(html)


class CheckmkRuleView(RuleModelView):
    """
    Custom Rule Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        self.column_formatters.update({
            'render_checkmk_outcome': _render_checkmk_outcome,
        })

        self.form_overrides.update({
            'render_checkmk_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_checkmk_outcome': "Checkmk Outcomes",
        })

        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            #'action_param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


_RULE_MNGMT_CARD_CSS = (
    '<style>'
    '.cmk-rule-card{max-width:100%;margin-bottom:6px;}'
    '.cmk-rule-card .card-title{font-size:0.95rem;margin:0;'
    'word-break:break-all;overflow-wrap:anywhere;}'
    '.cmk-rule-card .card-body{padding:8px 12px;}'
    '.cmk-rule-card ul{margin:4px 0 0;padding-left:20px;}'
    '.cmk-rule-card li{word-break:break-word;overflow-wrap:anywhere;}'
    '.cmk-rule-card .highlight{max-width:100%;overflow-x:auto;'
    'background:rgba(127,127,127,0.15);padding:2px 6px;border-radius:3px;'
    'display:inline-block;vertical-align:top;color:inherit;}'
    '.cmk-rule-card .highlight pre{margin:0;white-space:pre-wrap;'
    'word-break:break-all;}'
    '</style>'
)


def _render_rule_mngmt_outcome(_view, _context, model, _name):
    """
    Render Group Outcome — long ruleset names / value templates wrap
    inside the card instead of overflowing the table column.
    """
    html = [_RULE_MNGMT_CARD_CSS]
    for _idx, rule in enumerate(model.outcomes):
        value_template = highlight(
            rule.value_template, DjangoLexer(),
            HtmlFormatter(sytle='colorfull'),
        )
        html.append(f'''
           <div class="card cmk-rule-card">
             <div class="card-body">
               <h5 class="card-title mb-2">{escape(rule.ruleset)}</h5>
               <ul>
                <li><b>Template</b>: {value_template}</li>
        ''')
        if rule.loop_over_list:
            html.append(
                f'<li><b>Loop over</b>: {escape(rule.list_to_loop)}</li>'
            )
        html.append('</ul>')
        html.append(
            '<h6 class="card-subtitle mb-2 mt-2">Conditions:</h6><ul>'
        )
        if rule.condition_host:
            html.append(f'<li><b>Host</b>: {escape(rule.condition_host)}</li>')
        if rule.condition_label_template:
            html.append(
                f'<li><b>Host Label</b>: {escape(rule.condition_label_template)}</li>'
            )
        if rule.condition_service:
            html.append(
                f'<li><b>Service</b>: {escape(rule.condition_service)}</li>'
            )
        if rule.condition_service_label:
            html.append(
                f'<li><b>Service Label</b>: {escape(rule.condition_service_label)}</li>'
            )
        html.append('</ul></div></div>')
    return Markup(''.join(html))

class CheckmkGroupRuleView(RuleModelView):
    """
    Custom Group Model View
    """
    column_default_sort = "name"

    column_exclude_list = [
        'conditions', 'outcomes', 'outcome',
    ]

    form_subdocuments = {
        'outcome': {
            'form_overrides': {
                'foreach': StringField,
                'rewrite': StringField,
                'rewrite_title': StringField,
            },
            'form_widget_args': {
                'foreach': {
                    'placeholder': (
                        'Name of Attribute or Attribute Value, '
                        'depending on Foreach Type. You can use *'
                    )
                },
                'rewrite': {'placeholder': '{{name}}'},
                'rewrite_title': {'placeholder': '{{name}}'},
            }
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_groups"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Main Options',
                    'Name, description and activation.',
                    [rules.Field('name'),
                     rules.Field('documentation'),
                     rules.Field('enabled')]),
            section('2', 'out', 'Group Outcome',
                    'Create host/contact/service groups for hosts this '
                    'rule matches on.',
                    [rules.Field('outcome')]),
        ),
    ]


    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        # Default Form rules not match for the Fields of this Form
        #self.form_rules = []

        self.column_formatters.update({
            'render_checkmk_group_outcome': _render_group_outcome,
        })

        self.form_overrides.update({
            'render_checkmk_group_outcome': HiddenField,
            'name': StringField,
        })


        self.column_labels.update({
            'render_checkmk_group_outcome': "Create following Groups",
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



bi_rule_template = form_subdocuments_template.copy()
bi_rule_template.update({
        'outcomes' : {
            'form_subdocuments' : {
                '': {
                    'form_widget_args': {
                        'rule_template' : {"rows": 10},
                    },
                }
            }
        }
    })

class CheckmkBiRuleView(DefaultModelView):
    """
    Custom BI Rule View
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='BI Rule',
        outcome_desc='Business Intelligence rule pushed into Checkmk.',
    )

    form_excluded_columns = (
        'render_full_conditions',
        'render_cmk_bi_aggregation',
    )

    column_editable_list = [
        'enabled',
    ]

    form_subdocuments = bi_rule_template

    column_formatters = {
        'render_full_conditions': _render_full_conditions,
        'render_cmk_bi_rule': _render_bi_rule,
    }

    column_labels = {
        'render_cmk_bi_rule': "Rules",
        'render_full_conditions': "Conditions",
    }

    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    form_overrides = {
        'render_cmk_bi_rule': HiddenField,
    }

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Inputs
        """
        for rule in model.outcomes:
            rule.rule_template = rule.rule_template.replace('\\n',' ')
            rule.rule_template = rule.rule_template.replace('false','False')
            rule.rule_template = rule.rule_template.replace('true','True')

        return super().on_model_change(form, model, is_created)

    def __init__(self, model, **kwargs):
        """
        """
        #self.form_subdocuments = bi_rule_template
        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class FilterRulesetContains(BaseMongoEngineFilter):
    """Substring filter against any outcome's ruleset on a CheckmkRuleMngmt
    document. Uses `__raw__` because mongoengine's keyword form is
    fiddly on embedded ListField regex matches."""

    def apply(self, query, value):
        value = (value or '').strip()
        if not value:
            return query
        return query.filter(__raw__={
            'outcomes': {
                '$elemMatch': {
                    'ruleset': {'$regex': value, '$options': 'i'},
                },
            },
        })

    def operation(self):
        return "contains"


class CheckmkMngmtRuleView(RuleModelView):
    """
    Management of Rules inside Checkmk
    """
    list_template = 'admin/checkmk_rule_mngmt_list.html'

    # Group the listing by the rule's ruleset so rules of the same
    # Checkmk ruleset land next to each other. `primary_ruleset` is
    # denormalised in on_model_change; legacy rows are backfilled
    # lazily by `get_query` below. The field itself is hidden from
    # the form and the column list — operators only see/edit the
    # ruleset on the single outcome.
    column_default_sort = ('primary_ruleset', False)

    column_exclude_list = list(RuleModelView.column_exclude_list) + ['primary_ruleset']
    form_excluded_columns = ('primary_ruleset',)

    column_searchable_list = ('name', 'primary_ruleset', 'project')

    def init_search(self):
        """
        Bypass Flask-Admin's strict `type(p) in allowed_search_types`
        check — flask-mongoengine wraps StringField in a subclass that
        fails identity comparison and raises
        "Can only search on text columns. Failed to setup search for
        StringField …". Mirrors the same workaround used by
        `HostnameAndLabelSearchMixin` on the host views.
        """
        for name in self.column_searchable_list or []:
            field = self.model._fields.get(name) if isinstance(name, str) else name
            if field is None:
                raise ValueError(f"Invalid search field: {name!r}")
            self._search_fields.append(field)
        return bool(self._search_fields)

    def _search(self, query, search_term):
        """
        Match `name` OR `primary_ruleset` OR any outcome's `ruleset`.
        Without this override the toolbar quick-search would only hit
        the two top-level columns and miss rules whose ruleset the
        operator is typing — exactly what people expect when looking
        for "all my labels rules" or similar.
        """
        term = (search_term or '').strip()
        if not term:
            return query
        regex = {'$regex': term, '$options': 'i'}
        return query.filter(__raw__={
            '$or': [
                {'name': regex},
                {'primary_ruleset': regex},
                {'outcomes.ruleset': regex},
                {'project': regex},
            ],
        })

    def get_query(self):
        """Backfill `primary_ruleset` on legacy rows so existing data
        sorts/searches without a separate one-shot migration. Uses an
        atomic update per row instead of `.save()` so the partial
        `only('id', 'outcomes')` fetch can't trip Document-level
        validation (e.g. the required `name` field)."""
        legacy = CheckmkRuleMngmt.objects(
            primary_ruleset__exists=False,
        ).only('id', 'outcomes')
        for stale in legacy:
            value = stale.outcomes[0].ruleset if stale.outcomes else ''
            CheckmkRuleMngmt.objects(id=stale.id).update_one(
                set__primary_ruleset=value or '',
            )
        return super().get_query()

    column_filters = (
        FilterLike("name", 'Name'),
        FilterLike("project", 'Project'),
        BooleanEqualFilter("enabled", 'Enabled'),
        FilterRulesetContains("outcomes.ruleset", 'Ruleset'),
    )

    @expose('/_ruleset_choices')
    def ruleset_choices(self):
        """JSON list of distinct rulesets currently in use — feeds the
        ruleset filter's <datalist> autocomplete on the list view."""
        seen = set()
        for rule in CheckmkRuleMngmt.objects.only('outcomes.ruleset'):
            for outcome in rule.outcomes or []:
                if outcome.ruleset:
                    seen.add(outcome.ruleset)
        return {'rulesets': sorted(seen)}

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_setup_rules"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *_modern_rule_form(
            main_fields=[
                rules.Field('name'),
                rules.Field('documentation'),
                rules.Field('project'),
                div_open,
                rules.NestedRule(('enabled', 'last_match', 'static_rule')),
                div_close,
            ],
            condition_fields=[
                rules.Field('condition_typ'),
                rules.Field('conditions'),
            ],
            outcome_fields=[rules.Field('outcomes')],
            outcome_title='Checkmk Setup Rule',
            outcome_desc='The actual ruleset entry to create inside '
                         'Checkmk for matching hosts.',
        ),
    ]

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_rule_mngmt': _render_rule_mngmt_outcome,
        })

        self.form_overrides.update({
            'render_cmk_rule_mngmt': HiddenField,
            'project': ProjectSelectField,
        })

        self.column_labels.update({
            'render_cmk_rule_mngmt': "Create following Rules",
        })

        self.form_descriptions = dict(getattr(self, 'form_descriptions', {}) or {})
        self.form_descriptions['static_rule'] = (
            "Host-independent rule: render once and always create it, "
            "ignoring the host match conditions. Use only when the "
            "outcome templates reference no host attributes — it skips "
            "the per-host calculation entirely."
        )
        self.form_descriptions['project'] = (
            "Assign this rule to a Rule Project. Project rules are staged and "
            "pushed only through the project's test/prod workflow — they are "
            "left out of the global 'export_rules'."
        )

        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'ruleset': StringField,
                            'folder': StringField,
                            'condition_host': StringField,
                            'list_to_loop': StringField,
                            'value_template': StringField,
                            'condition_label_template': StringField,
                            'condition_service_label': StringField,
                            'condition_service': StringField,
                        },
                        'form_widget_args': {
                            'list_to_loop': {
                                'placeholder': (
                                    'You can enter an Attribute which contains a List.'
                                    ' Then the rule will be executed for every entry in this list.'
                                )
                            },
                            'value_template': {
                                'placeholder': (
                                    'Jinja. You can use {{loop}} to access variable'
                                    'when used in loop list mode'
                                )
                            },
                            'condition_label_template': {
                                'placeholder': (
                                    'Jinja. Need to return key:value'
                                )
                            },
                            'condition_host': {
                                'placeholder': (
                                    'Hostname for Condition, Supports'
                                    ' Comma Seperated Lists (or).'
                                    ' Use {{HOSTNAME}} for actual Host'
                                )
                            },
                            'condition_service': {
                                'placeholder': (
                                    'Service Name for Condition,'
                                    ' Supports Comma Seperated'
                                    ' Lists (or)'
                                )
                            },
                            'condition_service_label': {
                                'placeholder': (
                                    'Service Labels for Condition,'
                                    ' Supports Comma Seperated'
                                    ' Lists (and)'
                                )
                            },
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config


        super().__init__(model, **kwargs)

    def scaffold_form(self):
        """
        Build the form class normally, then drop `min_entries` on the
        `outcomes` inline list so the operator can remove every entry,
        including the last one. Patching the field's kwargs dict
        sidesteps the
        "got multiple values for keyword argument 'min_entries'"
        crash that `form_args` runs into.
        """
        form_class = super().scaffold_form()
        outcomes_field = getattr(form_class, 'outcomes', None)
        if outcomes_field is not None:
            outcomes_field.kwargs['min_entries'] = 0
        return form_class

    def validate_form(self, form):
        """
        Reject saves where outcomes target different rulesets. Doing
        the check here (instead of raising from `on_model_change`)
        keeps Flask-Admin's standard validation flow intact —
        the user sees a flash and stays on the edit form with their
        inputs preserved, instead of getting a raw 500.
        """
        if not super().validate_form(form):
            return False
        outcomes = getattr(form, 'outcomes', None)
        if outcomes is not None and getattr(outcomes, 'entries', None):
            rulesets = set()
            for entry in outcomes.entries:
                rs_field = entry.form.ruleset if hasattr(entry, 'form') else None
                if rs_field is None:
                    continue
                rulesets.add((rs_field.data or '').strip())
            if len(rulesets) > 1:
                seen = sorted(r for r in rulesets if r)
                flash(
                    'All outcomes on a rule must use the same Ruleset; '
                    f'got {", ".join(seen) or "(empty)"}. '
                    'Split into one rule per ruleset, or harmonise '
                    'the ruleset field on every outcome.',
                    'danger',
                )
                return False
        return True

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Inputs and refresh the denormalised primary_ruleset so
        the list view sorts/groups by it without re-reading the
        embedded outcomes. The uniform-ruleset rule is enforced in
        `validate_form` above; here we just trust the model.
        """
        for rule in model.outcomes:
            if rule.value_template[0] == '"':
                rule.value_template = rule.value_template[1:]
            if rule.value_template[-1] == '"':
                rule.value_template = rule.value_template[:-1]
            rule.value_template = rule.value_template.replace('\\n',' ')

        model.primary_ruleset = (
            model.outcomes[0].ruleset if model.outcomes else ''
        )

        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


def _render_project_rule_count(_view, _context, model, _name):
    """Assigned Setup-rule count, linking to the filtered Setup-rule list."""
    count = CheckmkRuleMngmt.objects(project=model.name).count()
    url = url_for('checkmkrulemngmt.index_view', flt0_1=model.name)
    return Markup(f'<a href="{escape(url)}">{count}</a>')


def _render_project_dcd_count(_view, _context, model, _name):
    """Assigned DCD-rule count, linking to the filtered DCD-rule list."""
    count = CheckmkDCDRule.objects(project=model.name).count()
    url = url_for('checkmkdcdrule.index_view', flt0_0=model.name)
    return Markup(f'<a href="{escape(url)}">{count}</a>')


def _render_project_name_link(_view, _context, model, _name):
    """Make the project name open its overview (rules + import/export)."""
    url = url_for('.overview_view', id=model.id)
    return Markup(f'<a href="{escape(url)}">{escape(model.name)}</a>')


def _render_project_accounts(_view, _context, model, _name):
    """List-column formatter: the accounts a project's rules are exported to."""
    if model.limit_by_accounts:
        return ', '.join(model.limit_by_accounts)
    return Markup('<em>all accounts</em>')


def _import_project_rules(model, rule_dicts, project_name):
    """
    (Re)create rules of one model from exported JSON dicts and assign them to
    ``project_name``. Existing rules with the same name are overwritten. Shared
    by the project JSON import for both Setup rules and DCD rules. Returns the
    number of rules imported.
    """
    count = 0
    for rule_data in rule_dicts or []:
        rule_data = dict(rule_data)
        rule_data.pop('_id', None)
        rule_name = rule_data.get('name')
        if not rule_name:
            continue
        existing = model.objects(name=rule_name).first()
        rule = model.from_json(json.dumps(rule_data))
        if existing:
            rule.id = existing.id
        rule.project = project_name
        rule.save()
        count += 1
    return count


class CheckmkRuleProjectView(DefaultModelView):
    """
    Rule Projects group Checkmk Setup Rules and limit where they are exported.
    ``limit_by_accounts`` restricts a project's rules to the listed Checkmk
    accounts during the normal rule export (empty = all accounts). Projects are
    im-/exportable as JSON to move them between separate syncer instances.
    """
    # Adds a direct link from the edit form to the Setup Rules of this project.
    edit_template = 'admin/checkmk_rule_project_edit.html'
    # Adds an "Import project from JSON" button to the list toolbar.
    list_template = 'admin/checkmk_rule_project_list.html'
    column_list = ('name', 'limit_by_accounts', 'rule_count', 'dcd_rule_count')
    column_default_sort = 'name'
    column_labels = {
        'rule_count': 'Rules',
        'dcd_rule_count': 'DCD Rules',
        'limit_by_accounts': 'Exported to Accounts',
    }
    column_formatters = {
        'name': _render_project_name_link,
        'rule_count': _render_project_rule_count,
        'dcd_rule_count': _render_project_dcd_count,
        'limit_by_accounts': _render_project_accounts,
    }
    column_filters = (
        FilterLike('name', 'Name'),
    )

    form_columns = ('name', 'documentation', 'limit_by_accounts')
    form_overrides = {
        'limit_by_accounts': CheckmkAccountsMultiSelectField,
    }
    form_descriptions = {
        'limit_by_accounts': "Export this project's rules only to these Checkmk "
                             "accounts. Leave empty to export them to every "
                             "account like ordinary rules.",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    @expose('/overview')
    def overview_view(self):
        """
        Project detail page: list the Setup Rules assigned to this project and
        surface the folder import and JSON export on one page — the row actions
        in the list are otherwise easy to miss.
        """
        project_id = request.args.get('id')
        project = self.get_one(project_id) if project_id else None
        if project is None:
            flash('Project not found', 'error')
            return redirect(self.get_url('.index_view'))
        project_rules = CheckmkRuleMngmt.objects(
            project=project.name).order_by('primary_ruleset', 'name')
        # DCD rules assigned to the project are shown for overview only — they
        # are not part of the Setup-rule export/import workflow.
        dcd_rules = CheckmkDCDRule.objects(
            project=project.name).order_by('name')
        return self.render(
            'admin/checkmk_rule_project_overview.html',
            project=project,
            project_rules=project_rules,
            dcd_rules=dcd_rules,
            return_url=self.get_url('.index_view'))

    @action('export', 'Export as JSON',
            'Download the selected projects and their rules as JSON?')
    def action_export(self, ids):
        """Bundle each selected project plus its rules into one JSON file."""
        payload = []
        for project in CheckmkRuleProject.objects(id__in=ids):
            project_rules = CheckmkRuleMngmt.objects(project=project.name)
            project_dcd_rules = CheckmkDCDRule.objects(project=project.name)
            payload.append({
                'project': json.loads(project.to_json()),
                'rules': [json.loads(rule.to_json()) for rule in project_rules],
                'dcd_rules': [json.loads(rule.to_json())
                              for rule in project_dcd_rules],
            })
        body = json.dumps(payload, indent=2, default=str)
        return Response(
            body, mimetype='application/json',
            headers={'Content-Disposition':
                     'attachment; filename=cmk_rule_projects.json'})

    @expose('/import', methods=['GET', 'POST'])
    def import_view(self):
        """Recreate a project and its rules from an exported JSON file."""
        return_url = self.get_url('.index_view')
        if request.method == 'GET':
            return self.render('admin/checkmk_rule_project_import.html',
                               return_url=return_url)

        upload = request.files.get('import_file')
        if not upload:
            flash('No file uploaded', 'error')
            return redirect(return_url)
        try:
            data = json.loads(upload.read().decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as error:
            flash(f'Invalid JSON: {error}', 'error')
            return redirect(return_url)

        # Accept a single {project, rules} object or a list of them.
        if isinstance(data, dict):
            data = [data]

        projects, imported_rules, imported_dcd_rules = 0, 0, 0
        for block in data:
            proj_data = dict((block or {}).get('project') or {})
            proj_data.pop('_id', None)
            name = proj_data.get('name')
            if not name:
                continue
            project = CheckmkRuleProject.objects(name=name).first() \
                or CheckmkRuleProject(name=name)
            project.documentation = proj_data.get('documentation')
            project.test_account = proj_data.get('test_account')
            project.prod_account = proj_data.get('prod_account')
            # An imported project always starts fresh — never inherit an
            # 'approved'/'live' status (or approver) from another instance.
            project.status = 'draft'
            project.approved_by = None
            project.approved_at = None
            project.save()
            projects += 1

            imported_rules += _import_project_rules(
                CheckmkRuleMngmt, block.get('rules'), name)
            imported_dcd_rules += _import_project_rules(
                CheckmkDCDRule, block.get('dcd_rules'), name)

        flash(f'Imported {projects} project(s), {imported_rules} rule(s) and '
              f'{imported_dcd_rules} DCD rule(s)', 'success')
        return redirect(return_url)

    @action('import_from_cmk', 'Import Rules from Checkmk Folder', None)
    def action_import_from_cmk(self, ids):
        """Row action: open the folder-import form for one selected project."""
        if len(ids) != 1:
            flash('Select exactly one project to import into', 'error')
            return redirect(request.referrer or url_for('.index_view'))
        return redirect(url_for('.import_from_cmk_view', id=ids[0]))

    @expose('/import_from_cmk', methods=['GET', 'POST'])
    def import_from_cmk_view(self):
        """
        Import every Checkmk Setup Rule of a chosen folder (on a chosen
        Checkmk account) into this project as static rules.
        """
        return_url = self.get_url('.index_view')
        project_id = request.args.get('id') or request.form.get('id')
        project = self.get_one(project_id) if project_id else None
        if project is None:
            flash('Select a project first', 'error')
            return redirect(return_url)

        if request.method == 'GET':
            accounts = [
                account.name for account in
                Account.objects(enabled=True, type='cmkv2').order_by('name')
            ]
            return self.render(
                'admin/checkmk_rule_project_import_cmk.html',
                project=project, project_id=project_id,
                accounts=accounts, return_url=return_url)

        account = request.form.get('account')
        folder = (request.form.get('folder') or '/').strip() or '/'
        recursive = bool(request.form.get('recursive'))
        if not account:
            flash('No Checkmk account selected', 'error')
            return redirect(return_url)

        # pylint: disable=import-outside-toplevel
        from .inits import import_project_rules_from_folder
        from .cmk2 import CmkException
        from .rule_passwords import referenced_password_names
        try:
            imported = import_project_rules_from_folder(
                project.name, account, folder, recursive)
        except CmkException as error_obj:
            flash(f"Checkmk import failed (account {account}): {error_obj}",
                  'error')
            return redirect(return_url)
        flash(
            f"Imported {imported} rule(s) from folder '{folder}' "
            f"(account {account})",
            'success' if imported else 'warning')
        # Rules that carried an explicit password were rewritten to reference
        # the syncer password store — tell the user which entries to create so
        # they deploy with the project.
        referenced = set().union(*(
            referenced_password_names(outcome.value_template)
            for rule in CheckmkRuleMngmt.objects(project=project.name)
            for outcome in rule.outcomes))
        if referenced:
            flash(
                "These rules reference password store entries: "
                f"{', '.join(sorted(referenced))}. Create a Checkmk Password "
                "in the syncer with each name (real secret), then run the "
                "password export so the reference resolves in the target "
                "Checkmk.",
                'warning')
        return redirect(return_url)


class CheckmkSiteView(DefaultModelView):
    """
    Checkmk Site Management Config
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    column_default_sort = "name"


    column_editable_list = [
        'enabled',
    ]

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name of the Checkmk site, description and activation.',
                [rules.Field('name'),
                 rules.Field('documentation'),
                 rules.Field('enabled')]),
        section('2', 'cond', 'Connection',
                'Server address and the Site Settings template to '
                'inherit (edition, version, certs, …).',
                [rules.Field('server_address'),
                 rules.Field('settings_master')]),
        section('3', 'out', 'Ansible Overrides',
                'Per-site custom Ansible variables applied on top of '
                'the Site Settings defaults.',
                [rules.Field('custom_ansible_variables')]),
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


class CheckmkTagMngmtView(DefaultModelView):
    """
    Checkmk Tag Management
    """

    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }
    form_widget_args = {
        'group_topic_name': {
            'placeholder': 'Name of Topic for Hosttags in Checkmk'
        },
        'group_title': {
            'placeholder': 'Groups Title'
        },
        'rewrite_title': {
            'placeholder': '{{name}}'
        },
        'rewrite_id': {
            'placeholder': '{{name}}'
        },
        'group_multiply_list': {
            'placeholder': (
                'Name of Attribute containing the list of values to '
                'create multiple groups'
            )
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_hosttags"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Checkmk Group Data',
                    'Topic, title, id and help text that appear in '
                    'Checkmk Setup.',
                    [rules.Field('group_topic_name'),
                     rules.Field('group_title'),
                     rules.Field('group_id'),
                     rules.Field('group_help')]),
            section('2', 'cond', 'ID & Title Rewrites',
                    'Define which ID and title the tag should have in Checkmk.',
                    [rules.Field('rewrite_id'),
                     rules.Field('rewrite_title'),
                     rules.Field('enabled')]),
            section('3', 'aux', 'Additional Options',
                    'Create multiple groups, filter input, internal notes.',
                    [rules.Field('group_multiply_list'),
                     rules.Field('group_multiply_by_list'),
                     rules.Field('filter_by_account'),
                     rules.Field('documentation')]),
        ),
    ]

    form_overrides = {
        'group_topic_name': StringField,
        'group_title': StringField,
        'group_id': StringField,
        'group_help': StringField,
    }

    column_exclude_list = [
        'documentation', 'group_help',

    ]
    column_editable_list = [
        'enabled',
    ]

    column_formatters = {
            'rewrite_id': _render_jinja,
            'rewrite_title': _render_jinja,
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class CheckmkUserMngmtView(DefaultModelView):
    """
    Checkmk User Management
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }


    column_exclude_list = [
        'password', 'email',
        'pager_address'
    ]

    column_editable_list = [
        'disabled',
        'remove_if_found',
        'disable_login'
    ]

    form_rules = modern_form(
        section('1', 'main', 'Identity',
                'Login ID, name and contact — these are the fields '
                'Checkmk shows in the user list.',
                [rules.Field('user_id'),
                 rules.Field('full_name'),
                 rules.Field('email'),
                 rules.Field('pager_address'),
                 rules.Field('documentation')]),
        section('2', 'cond', 'Roles & Groups',
                'Which Checkmk roles and contact groups this user '
                'belongs to.',
                [rules.Field('roles'),
                 rules.Field('contact_groups')]),
        section('3', 'out', 'Authentication',
                'Password handling and login state on the Checkmk side.',
                [rules.Field('password'),
                 rules.Field('overwrite_password'),
                 rules.Field('force_password_change'),
                 rules.Field('disable_login')]),
        section('4', 'aux', 'Lifecycle',
                'Sync flags controlling how this user entry reacts to '
                'the Checkmk state.',
                [rules.Field('remove_if_found'),
                 rules.Field('disabled')]),
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class CheckmkSettingsView(DefaultModelView):
    """
    Checkmk Server Settings View
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_widget_args = {
        'cmk_version_filename': {
            'placeholder': (
                'Filename of installation file. '
                'You can use {{CMK_VERSION}} and {{CMK_EDITION}} as placeholders'
            )
        },
        'cmk_version': {
            'placeholder': "Target Checkmk Version Number",
        },
        'installation_staging_path': {
            'placeholder': (
                "Directory to stage the downloaded installer in (default "
                "/tmp). Set a custom path if the executing user can't use "
                "/tmp — e.g. permission or private-tmp isolation issues."
            ),
        },
        'server_user': {
            'placeholder': "User to connect to server where the site is running",
        },
        'inital_password': {
            'placeholder': "Initial Passwort if we need to create the site",
        },
        'subscription_username': {
            'placeholder': (
                "Enter Data if you want the syncer to download this "
                "Versions directly from checkmk"
            ),
        },
        'cmk_user': {
            'placeholder': (
                "API user for CheckMK automation"
                " (for downtime management)."
                " You can use {{ACCOUNT:x:username}}"
                " as Placeholder"
            ),
        },
        'cmk_secret': {
            'placeholder': (
                "API secret/password for CheckMK"
                " automation ({{ACCOUNT:x:password}}"
            ),
        },
        'cmk_server_address': {
            'placeholder': (
                "CheckMK server address for API calls"
                " (with site, or {{ACCOUNT:x:address}})"
            ),
        },
        'webserver_certificate': {
            'placeholder': (
                "Optional: Add Paths to your Webserver Certificate Files "
                "to automaticly update them if needed"
            ),
        },
    }

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name, documentation and the Ansible user for site ops.',
                [rules.Field('name'),
                 rules.Field('documentation'),
                 rules.Field('server_user')]),
        section('2', 'cond', 'Checkmk Site',
                'Edition, version, filename and initial password — used '
                'when rolling out a fresh site.',
                [rules.Field('cmk_edition'),
                 rules.Field('cmk_version'),
                 rules.Field('cmk_version_filename'),
                 rules.Field('installation_staging_path'),
                 rules.Field('inital_password')]),
        section('3', 'out', 'Checkmk API',
                'Optional: credentials + API address for automated '
                'downtimes / status reads.',
                [rules.Field('cmk_user'),
                 rules.Field('cmk_secret'),
                 rules.Field('cmk_server_address')]),
        section('4', 'aux', 'Automatic Download & Certificates',
                'Optional: subscription creds for auto-version-download '
                'and paths to webserver certs for auto-renewal.',
                [rules.Field('subscription_username'),
                 rules.Field('subscription_password'),
                 rules.Field('webserver_certificate'),
                 rules.Field('webserver_certificate_private_key'),
                 rules.Field('webserver_certificate_intermediate')]),
    )

    column_exclude_list = [
        'inital_password',
        'subscription_username',
        'subscription_password',
        'cmk_secret',
    ]

    column_sortable_list = (
        'name',
    )

    def on_model_delete(self, model):
        """
        Prevent deletion of Sites with Assignes configs
        """
        for site in CheckmkSite.objects():
            if site.settings_master == model:
                raise ValidationError(f"Can't delete: Still used by a Siteconfig {site.name}")

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    list_template = 'admin/checkmk_settings_list.html'

    # Modernized list template intercepts the action client-side and
    # opens a modal instead of navigating to /set_cmk_version_form.
    # The redirect path below remains as a graceful fallback for
    # JS-disabled clients.
    @action('set_cmk_version', 'Set CMK Version', None)
    def action_set_cmk_version(self, ids):
        """
        Action to set CMK Version for selected Entries
        """
        url = url_for('.set_cmk_version_form', ids=','.join(ids))
        return redirect(url)

    @expose('/set_cmk_version_form')
    def set_cmk_version_form(self):
        """
        Custom form for CMK Version selection
        """
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',')]

        return render_template('admin/set_cmk_version_form.html', ids=ids)

    @expose('/process_cmk_version_assignment', methods=['POST'])
    def process_cmk_version_assignment(self):
        """
        Process the CMK Version assignment
        """
        rule_ids = request.form.get('rule_ids', '').split(',')
        cmk_version = request.form.get('cmk_version', '').strip()

        if not cmk_version:
            flash('Please enter a CMK Version', 'error')
            return redirect(url_for('.index_view'))

        updated_count = 0
        try:
            for rule_id in rule_ids:
                if not rule_id.strip():
                    continue
                entry = CheckmkSettings.objects(id=rule_id).first()
                if entry:
                    entry.cmk_version = cmk_version
                    entry.save()
                    updated_count += 1
            flash(f'CMK Version "{cmk_version}" applied to {updated_count} entries', 'success')
        except (ValueError, ValidationError) as e:
            flash(f'Error applying CMK Version: {str(e)}', 'error')

        return redirect(url_for('.index_view'))


class CheckmkFolderPoolView(DefaultModelView):
    """
    Folder Pool Model
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    column_default_sort = "folder_name"

    column_editable_list = [
        'enabled',
    ]

    column_filters = (
       FilterLike(
            "folder_name",
           'Folder Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    form_widget_args = {
        'folder_seats_taken': {'disabled': True},
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    def on_model_change(self, form, model, is_created):
        """
        Make Sure Folder are saved correct
        """

        if not  model.folder_name.startswith('/'):
            model.folder_name = "/" + model.folder_name

        return super().on_model_change(form, model, is_created)

class CheckmkDowntimeView(RuleModelView):
    """
    Checkmk Downtimes
    """
    # Custom Form Rules because default needs the sort_field which we not have
    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='Downtime',
        outcome_desc='Schedule a Checkmk downtime window for matching hosts.',
    )

    column_labels = {
        'render_cmk_downtime_rule': "Downtimes",
        'render_full_conditions': "Conditions",
    }

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_downtime_rule': _render_dw_rule,
        })

        self.form_overrides.update({
            'render_cmk_downtime_rule': HiddenField,
            'name': StringField,
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

_NOTIFICATION_LIST_LABELS = [
    ('match_contact_groups', 'Filter Contact Groups'),
    ('match_host_groups', 'Filter Host Groups'),
    ('match_service_groups', 'Filter Service Groups'),
    ('match_sites', 'Filter Sites'),
    ('match_folder', 'Filter Folder'),
    ('match_hosts', 'Filter Hosts'),
    ('match_exclude_hosts', 'Exclude Hosts'),
    ('match_services', 'Filter Services'),
    ('match_exclude_services', 'Exclude Services'),
    ('match_host_labels', 'Filter Host Labels'),
    ('match_service_labels', 'Filter Service Labels'),
    ('match_host_tags', 'Filter Host Tags'),
    ('match_check_types', 'Filter Check Types'),
    ('match_plugin_output', 'Filter Plugin Output'),
    ('match_only_during_time_period', 'Filter Time Period'),
    ('match_service_levels', 'Filter Service Levels'),
    ('match_contacts', 'Filter Contacts'),
]


def _render_notification_rule(_view, _context, model, _name):
    """
    Compact key/value listing of a notification rule's outcomes for
    the Flask-Admin list column.
    """
    # pylint: disable=import-outside-toplevel
    from .notification_rules import (
        HOST_EVENT_TYPE_CHOICES, SERVICE_EVENT_TYPE_CHOICES)
    host_labels = dict(HOST_EVENT_TYPE_CHOICES)
    svc_labels = dict(SERVICE_EVENT_TYPE_CHOICES)

    html = [_RULE_MNGMT_CARD_CSS]
    for entry in model.outcomes:
        rows = [('Method', entry.notification_method or 'mail')]
        if entry.contact_group_recipients:
            rows.append(('Recipients', entry.contact_group_recipients))
        for field, label in _NOTIFICATION_LIST_LABELS:
            value = getattr(entry, field, None)
            if value:
                rows.append((label, value))
        if entry.match_host_event_types:
            rows.append(('Host events', ', '.join(
                host_labels.get(f, f) for f in entry.match_host_event_types)))
        if entry.match_service_event_types:
            rows.append(('Service events', ', '.join(
                svc_labels.get(f, f) for f in entry.match_service_event_types)))
        if entry.disable_rule:
            rows.append(('Disabled', 'yes'))
        items = ''.join(
            f'<li><b>{escape(label)}</b>: {escape(value)}</li>'
            for label, value in rows
        )
        html.append(
            '<div class="card cmk-rule-card"><div class="card-body">'
            f'<ul>{items}</ul>'
            '</div></div>'
        )
    return Markup(''.join(html))


class _NotificationMethodWidget:
    """Render a free-text input with a <datalist> of built-in plugins
    so admins get autocomplete suggestions but can still type any
    custom notification plugin name."""
    # pylint: disable=too-few-public-methods

    def __call__(self, field, **kwargs):
        # pylint: disable=import-outside-toplevel
        from .notification_rules import NOTIFICATION_METHOD_SUGGESTIONS
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('class', 'form-control')
        list_id = f'{field.id}_suggestions'
        value = field.data or ''
        options = ''.join(
            f'<option value="{escape(name)}">' for name in NOTIFICATION_METHOD_SUGGESTIONS
        )
        return Markup(
            f'<input type="text" name="{field.name}" '
            f'id="{kwargs["id"]}" class="{kwargs["class"]}" '
            f'list="{list_id}" value="{escape(value)}" '
            f'placeholder="mail, slack, msteams, custom_script_name, …">'
            f'<datalist id="{list_id}">{options}</datalist>'
        )


class _StringFieldWithDatalist(StringField):
    """StringField that renders with the datalist widget above."""
    widget = _NotificationMethodWidget()


class _CheckboxMultiWidget:
    """
    Render a SelectMultipleField as a contained, scrollable
    Bootstrap form-check group so the checkboxes don't overflow into
    the surrounding inputs (which the wtforms ListWidget did) and
    remain unambiguously multi-select (Flask-Admin's default Select2
    hijacks a plain ``<select multiple>`` to single-select).
    """
    # pylint: disable=too-few-public-methods

    def __call__(self, field, **_kwargs):
        selected = set(field.data or [])
        parts = [
            '<div class="cmk-event-checkboxes" '
            'style="max-height:220px;overflow-y:auto;padding:8px 12px;'
            'border:1px solid var(--bs-border-color, #ced4da);'
            'border-radius:4px;">'
        ]
        for value, label in field.choices:
            cid = f'{field.id}-{value}'
            check = ' checked' if value in selected else ''
            parts.append(
                f'<div class="form-check">'
                f'<input class="form-check-input" type="checkbox" '
                f'name="{field.name}" id="{cid}" '
                f'value="{escape(value)}"{check}>'
                f'<label class="form-check-label" for="{cid}">'
                f'{escape(label)}</label>'
                f'</div>'
            )
        parts.append('</div>')
        return Markup(''.join(parts))


class _CheckboxMultiField(SelectMultipleField):
    widget = _CheckboxMultiWidget()


def _host_event_select(*args, **kwargs):
    # pylint: disable=import-outside-toplevel
    from .notification_rules import HOST_EVENT_TYPE_CHOICES
    kwargs.setdefault('choices', HOST_EVENT_TYPE_CHOICES)
    return _CheckboxMultiField(*args, **kwargs)


def _service_event_select(*args, **kwargs):
    # pylint: disable=import-outside-toplevel
    from .notification_rules import SERVICE_EVENT_TYPE_CHOICES
    kwargs.setdefault('choices', SERVICE_EVENT_TYPE_CHOICES)
    return _CheckboxMultiField(*args, **kwargs)


class CheckmkNotificationRuleView(RuleModelView):
    """
    Custom Notification Rule Model View
    """
    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
            rules.Field('sort_field'),
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='Notification Rule',
        outcome_desc='One Checkmk notification rule body, rendered '
                     'against each matching host\'s attributes. '
                     'Empty fields disable the corresponding condition.',
    )

    column_labels = {
        'render_cmk_notification_rule': "Notification Rules",
        'render_full_conditions': "Conditions",
    }

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        self.column_formatters.update({
            'render_cmk_notification_rule': _render_notification_rule,
        })

        self.form_overrides.update({
            'render_cmk_notification_rule': HiddenField,
            'name': StringField,
        })

        base_config = dict(self.form_subdocuments)
        match_field_overrides = {
            field: StringField for field, _label in _NOTIFICATION_LIST_LABELS
        }
        match_field_overrides['contact_group_recipients'] = StringField
        match_field_overrides['notification_method'] = _StringFieldWithDatalist
        # Multi-select with human-readable labels for the event-type
        # ListFields. wtforms posts a plain list of API-flag strings.
        match_field_overrides['match_host_event_types'] = _host_event_select
        match_field_overrides['match_service_event_types'] = _service_event_select

        # Form labels — drop the noisy "Match" prefix; the section
        # context already says these are match conditions.
        form_args = {
            field: {'label': label}
            for field, label in _NOTIFICATION_LIST_LABELS
        }
        form_args['contact_group_recipients'] = {'label': 'Contact Group Recipients'}
        form_args['notification_method'] = {'label': 'Notification Method'}
        form_args['match_host_event_types'] = {'label': 'Filter Host Event Types'}
        form_args['match_service_event_types'] = {'label': 'Filter Service Event Types'}
        form_args['disable_rule'] = {'label': 'Disable Rule'}
        base_config.update({
            'outcomes': {
                'form_subdocuments': {
                    '': {
                        'form_overrides': match_field_overrides,
                        'form_args': form_args,
                        'form_widget_args': {
                            'contact_group_recipients': {
                                'placeholder': (
                                    'Comma-separated CG names, Jinja. '
                                    'e.g. {{cmk_contact_group}}_ALARM'
                                )
                            },
                            'match_contact_groups': {
                                'placeholder': (
                                    'Comma-separated CG names, Jinja. '
                                    'e.g. {{cmk_contact_group}}'
                                )
                            },
                            'match_host_groups': {
                                'placeholder': 'Comma-separated host group names, Jinja',
                            },
                            'match_service_groups': {
                                'placeholder': 'Comma-separated service group names, Jinja',
                            },
                            'match_sites': {
                                'placeholder': 'Comma-separated site IDs, Jinja',
                            },
                            'match_folder': {
                                'placeholder': 'Single folder path (subfolders matched), Jinja',
                            },
                            'match_hosts': {
                                'placeholder': 'Comma-separated host names, Jinja',
                            },
                            'match_exclude_hosts': {
                                'placeholder': 'Comma-separated host names, Jinja',
                            },
                            'match_services': {
                                'placeholder': (
                                    'Comma-separated service descriptions / regex, Jinja'),
                            },
                            'match_exclude_services': {
                                'placeholder': (
                                    'Comma-separated service descriptions / regex, Jinja'),
                            },
                            'match_host_labels': {
                                'placeholder': 'Comma-separated key:value pairs, Jinja',
                            },
                            'match_service_labels': {
                                'placeholder': 'Comma-separated key:value pairs, Jinja',
                            },
                            'match_host_tags': {
                                'placeholder': 'Comma-separated tag_group:tag_id pairs, Jinja',
                            },
                            'match_check_types': {
                                'placeholder': 'Comma-separated check plugin names, Jinja',
                            },
                            'match_plugin_output': {
                                'placeholder': 'Regex against service plugin output, Jinja',
                            },
                            'match_only_during_time_period': {
                                'placeholder': 'Single time period name, Jinja',
                            },
                            'match_service_levels': {
                                'placeholder': 'Range "min,max" (numeric), Jinja',
                            },
                            'match_contacts': {
                                'placeholder': 'Comma-separated user IDs, Jinja',
                            },
                        },
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


class CheckmkCacheView(DefaultModelView):
    """
    Checkmk Cache View
    """
    can_create = False
    can_edit = False
    show_details = True

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkDCDView(RuleModelView):
    """
    Custom DCD Rule View
    """

    column_editable_list = [
        'enabled',

    ]

    column_labels = {
        'render_cmk_dcd_rule': "DCD Rules",
        'render_full_conditions': "Conditions",
    }

    column_filters = (
        FilterLike('project', 'Project'),
    )

    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            rules.Field('project'),
            div_open,
            rules.NestedRule(('enabled', 'last_match', 'static_rule')),
            div_close,
            rules.Field('sort_field'),
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='DCD Rule',
        outcome_desc='The DCD connection(s) to create in Checkmk.',
    )

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_dcd_rule': _render_dcd_rule,
        })

        self.form_overrides.update({
            'render_cmk_dcd_rule': HiddenField,
            'project': ProjectSelectField,
        })

        self.form_descriptions = dict(getattr(self, 'form_descriptions', {}) or {})
        self.form_descriptions['project'] = (
            "Assign this DCD rule to a Rule Project. It then shows up on the "
            "project overview and follows the project's account filter — the "
            "rule is exported only to the accounts the project allows (a "
            "project without an account filter still exports everywhere)."
        )
        self.form_descriptions['static_rule'] = (
            "Host-independent rule: render it once and always create it, "
            "ignoring the match conditions. A DCD connection rarely depends on "
            "host data, so this skips the per-host calculation and is much "
            "faster on large inventories. Use only when the outcome templates "
            "reference no host attributes."
        )

        # Hint the {{ cmk_site }} macro in the outcome's Site field so users see
        # they can target the exporting account's own Checkmk site (test/prod).
        base_subdocs = dict(getattr(self, 'form_subdocuments', None) or {})
        base_subdocs['outcomes'] = {
            'form_subdocuments': {
                '': {
                    'form_widget_args': {
                        'site': {
                            'placeholder':
                                '{{ cmk_site }} — the exporting account\'s site',
                        },
                    },
                },
            },
        }
        self.form_subdocuments = base_subdocs

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkInventorizeAttributesView(DefaultModelView):
    """
    Form rules for Inventorize Attributes
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_inventory_attributes"]}" '
                   f'target="_blank" class="badge badge-light" '
                   f'style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Attributes to Inventorize',
                    'Which host attributes to pull from Checkmk into '
                    'the syncer inventory. For source <code>HW/SW '
                    'Inventory</code> the full Checkmk inventory tree is '
                    'additionally stored under <em>Host → Inventory Tree</em>; '
                    'only the paths listed here are promoted to '
                    '<code>Host.inventory</code> for the rule engine.',
                    [rules.Field('attribute_names'),
                     rules.Field('attribute_source')]),
        ),
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkPasswordView(DefaultModelView):
    """
    Checkmk Password View
    """

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_password_store"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Basics',
                    'Internal name, notes and activation.',
                    [rules.Field('name'),
                     rules.Field('documentation'),
                     rules.Field('enabled')]),
            section('2', 'out', "Checkmk Password Store",
                    'Fields synced into Checkmk\'s built-in password store.',
                    [rules.Field('title'),
                     rules.Field('comment'),
                     rules.Field('documentation_url'),
                     rules.Field('owner'),
                     rules.Field('password'),
                     rules.Field('shared')]),
        ),
    ]

    column_filters = (
       FilterLike(
            "title",
           'Title'
       ),
       FilterLike(
            "comment",
           'Comment'
       ),
    )

    column_editable_list = [
        'enabled'

    ]

    form_excluded_columns = [
       "password_crypted"
    ]

    column_exclude_list = [
        'password_crypted', 'shared', 'documentation_url',
        'owner',
    ]

    def scaffold_form(self):
        form_class = super().scaffold_form()
        form_class.password = PasswordField("Password")
        return form_class

    def on_model_change(self, form, model, is_created):
        if form.password.data:
            model.set_password(form.password.data)
        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


def _get_custom_field(account, name):
    """Read a custom_fields value off an Account (empty string if unset)."""
    for entry in account.custom_fields:
        if entry.name == name:
            return entry.value or ''
    return ''


def _set_custom_field(account, name, value):
    """Set (or create) a custom_fields entry on an Account in place."""
    for entry in account.custom_fields:
        if entry.name == name:
            entry.value = value
            return
    entry = CustomEntry()
    entry.name = name
    entry.value = value
    account.custom_fields.append(entry)


class CheckmkTestFolderScopeView(BaseView):
    """
    Limit a single Checkmk account's host export to selected folders.

    The host export reads ``limit_by_folders`` off the exported account, so the
    account only receives the hosts of the chosen folders (subfolders included).
    This only ever touches the one account selected here — no other account
    (production or otherwise) is affected. Accounts without a folder scope keep
    exporting every host as before. Folders can be picked from those the
    configured rules produce, and additional custom folders can be typed in.
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    def _render(self, selected_account):
        """Render the picker for the (optionally) chosen account."""
        # pylint: disable=import-outside-toplevel
        from .cmk_rules import iter_rule_folders, scope_folder
        # Carry each account's scope state so the dropdown makes clear which
        # accounts have the folder limit active and which export every host.
        accounts = []
        for account in Account.objects(enabled=True, type='cmkv2').order_by('name'):
            raw = _get_custom_field(account, 'limit_by_folders')
            accounts.append({
                'name': account.name,
                'scoped': bool([x for x in raw.split(',') if x.strip()]),
            })
        account = None
        chosen = []
        rule_folders = iter_rule_folders()
        if selected_account:
            account = Account.objects(name=selected_account, type='cmkv2').first()
        if account:
            raw = _get_custom_field(account, 'limit_by_folders')
            # Normalise the saved scope the same way as the rule folders so old
            # mixed-case entries line up with the (lowercase) rule folders in the
            # UI and stay de-duplicated.
            chosen = []
            for entry in raw.split(','):
                if not entry.strip():
                    continue
                folder = scope_folder(entry)
                if folder not in chosen:
                    chosen.append(folder)
        return self.render(
            'admin/checkmk_test_folder_scope.html',
            accounts=accounts,
            selected_account=account.name if account else '',
            scope_enabled=bool(chosen),
            rule_folders=rule_folders,
            chosen=chosen,
            lowercase_folders=app.config['CMK_LOWERCASE_FOLDERNAMES'])

    @expose('/', methods=['GET', 'POST'])
    def index(self):
        """Show the picker and save the folder scope of the chosen account."""
        if request.method == 'GET':
            return self._render(request.args.get('account'))

        from .cmk_rules import scope_folder  # pylint: disable=import-outside-toplevel
        account_name = request.form.get('account')
        account = Account.objects(name=account_name, type='cmkv2').first() \
            if account_name else None
        if account is None:
            flash('Select a Checkmk account first', 'error')
            return redirect(self.get_url('.index'))

        # The form submits the whole selection (rule folders + typed-in ones) as
        # a single ``folders`` list; normalise, lowercase and de-duplicate it.
        folders = []
        for entry in request.form.getlist('folders'):
            if not entry.strip():
                continue
            folder = scope_folder(entry)
            if folder not in folders:
                folders.append(folder)

        _set_custom_field(account, 'limit_by_folders', ','.join(folders))
        account.save()
        flash(f"Saved {len(folders)} folder(s) for account '{account.name}'. "
              f"Its host export is now limited to these folders.", 'success')
        return redirect(self.get_url('.index', account=account.name))
