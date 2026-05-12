"""
Jira Cloud Export — Flask-Admin views.

The outcome's ``jira_attribute`` and the rule's ``object_type_id`` are
rendered as Select2-backed dropdowns whose choices come from the
``JiraSchemaCache`` populated by ``cmdbsyncer jira sync_schema``.  That
gives autocomplete in the GUI without doing a live Jira call on every
page render.
"""
# pylint: disable=no-name-in-module,duplicate-code
from flask_admin.form import rules
from flask_admin.form.fields import Select2Field
from flask_login import current_user
from markupsafe import Markup, escape
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer
from wtforms import HiddenField, StringField

from application.modules.rule.views import FiltereModelView, RuleModelView
from application.views.default import DefaultModelView
from application.plugins.jira_cloud.models import JiraSchemaCache


def _target_choices():
    """
    Every (object_type, attribute) pair the schema cache knows about,
    as ``("<type_id>|<attr_name>", "Schema / Type / Attribute")``.

    Object type and attribute are stored as one combined ``target``
    string because in Jira Assets an attribute belongs to its type —
    "Name" on Hardware Server is a different attribute from "Name" on
    Laptop, with different ids — so the user picks them as a single
    target rather than two independent fields that could disagree.
    """
    rows = [('', '-- run jira sync_schema first --')]
    seen = set()
    for cache in JiraSchemaCache.objects():
        for otype in sorted(cache.object_types,
                            key=lambda x: ((x.schema_name or '').lower(),
                                           (x.name or '').lower())):
            type_label = f"{otype.schema_name or '?'} / {otype.name}"
            for attr in sorted(otype.attributes,
                               key=lambda a: (a.name or '').lower()):
                if not attr.name:
                    continue
                value = f"{otype.object_type_id}|{attr.name}"
                if value in seen:
                    continue
                seen.add(value)
                rows.append((value, f"{type_label} / {attr.name}"))
    return rows


class _TargetSelectField(Select2Field):
    """
    Select2-backed dropdown holding the combined ``object_type / attribute``
    pair.  Select2 gives in-place type-ahead search so the user can
    filter ~3000 (type × attribute) entries by typing.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', _target_choices)
        super().__init__(*args, **kwargs)

    def pre_validate(self, _form):
        # Schema cache may have been re-synced after the rule was saved,
        # so the persisted target may no longer appear in `choices()`.
        # Don't reject it on edit; the export run logs an "unknown
        # attribute" warning when it actually mismatches the cache.
        return


def _render_outcomes(_view, _context, model, _name):
    """Compact card list for the rule overview column."""
    html = ""
    type_names = {}
    for cache in JiraSchemaCache.objects():
        for otype in cache.object_types:
            type_names[otype.object_type_id] = f"{otype.schema_name} / {otype.name}"
    for entry in model.outcomes:
        type_id = entry.object_type_id
        type_label = (type_names.get(type_id, f"type {type_id}")
                      if type_id is not None else "(no target)")
        attr = escape(entry.jira_attribute or '')
        value_html = ""
        if entry.value:
            value_html = highlight(str(entry.value), DjangoLexer(),
                                   HtmlFormatter(sytle='colorfull'))
        html += f'''
            <div class="card">
              <div class="card-body">
                <h6 class="card-subtitle mb-2 text-muted">
                  <span class="badge badge-info">{escape(type_label)}</span>
                  {attr}
                </h6>
                <p class="card-text">{value_html}</p>
              </div>
            </div>
        '''
    return Markup(html)


class JiraExportRuleView(RuleModelView):
    """Flask-Admin view for JiraExportRule."""

    column_list = (
        'name', 'enabled', 'sort_field',
        'render_jira_export_outcome',
    )

    column_labels = {
        'render_jira_export_outcome': "Field Mapping",
    }

    def __init__(self, model, **kwargs):
        self.column_formatters.update({
            'render_jira_export_outcome': _render_outcomes,
        })
        self.form_overrides.update({
            'render_jira_export_outcome': HiddenField,
        })

        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments': {
                    '': {
                        'form_overrides': {
                            'target': _TargetSelectField,
                            'value': StringField,
                        },
                        'form_widget_args': {
                            'value': {'size': 60},
                        },
                    },
                },
            },
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    form_rules = [
        rules.FieldSet(('name', 'documentation', 'enabled',
                        'sort_field', 'last_match'),
                       "Main Options"),
        rules.FieldSet(('condition_typ', 'conditions'),
                       "Conditions"),
        rules.FieldSet(('outcomes',), "Field Mapping"),
    ]

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('jira')


class JiraCloudFilterView(FiltereModelView):
    """
    Filter view for the Jira Cloud export.

    The shared FilterAction supports whitelist_attribute /
    whitelist_attribute_value too, but for this plugin the attributes
    are already declared explicitly in the Export Rule's Field Mapping
    — so we constrain the action to ``ignore_hosts`` and hide the
    attribute name field that comes with it.
    """

    def __init__(self, model, **kwargs):
        base_config = dict(getattr(self, 'form_subdocuments', {}))
        base_config.update({
            'outcomes': {
                'form_subdocuments': {
                    '': {
                        'form_args': {
                            'action': {
                                'choices': [('ignore_hosts',
                                             'Ignore Matching Hosts')],
                            },
                        },
                        'form_overrides': {
                            'attribute_name': HiddenField,
                        },
                    },
                },
            },
        })
        self.form_subdocuments = base_config
        super().__init__(model, **kwargs)

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('jira')


def _render_schema_summary(_view, _context, model, _name):
    """Compact list of cached types per account."""
    rows = []
    for otype in sorted(model.object_types,
                        key=lambda x: ((x.schema_name or '').lower(),
                                       (x.name or '').lower())):
        rows.append(
            f"<li><b>{escape(otype.schema_name or '?')}</b> / "
            f"{escape(otype.name)} "
            f"<small class='text-muted'>"
            f"#{otype.object_type_id} · {len(otype.attributes)} attrs"
            f"</small></li>"
        )
    return Markup("<ul>" + "".join(rows) + "</ul>")


class JiraSchemaCacheView(DefaultModelView):
    """Read-only view of the cached schema."""

    can_create = False
    can_edit = False
    can_delete = True

    column_list = ('account', 'updated', 'render_summary')
    column_labels = {'render_summary': "Object Types"}
    column_formatters = {
        'render_summary': _render_schema_summary,
    }

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_right('jira')
