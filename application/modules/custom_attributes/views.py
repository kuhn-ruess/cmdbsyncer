"""
Custom Attribute Rule Model View
"""
import json

from flask import g, jsonify, request
from flask_admin import expose
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import StringField
from application.helpers.sates import add_changes
from application.models.user import is_readonly
from application.modules.rule.views import (RuleModelView, _render_attribute_outcomes,
                                            invalidate_host_rule_caches)
from application.modules.custom_attributes import ordering


def _order_info(view):
    """
    Position, group gaps and ties of every rule, computed once per request.

    The list may be filtered, the positions are those of the full rule set,
    the order the rules really run in.
    """
    cache = g.setdefault('custom_attribute_order', {})
    if view.endpoint not in cache:
        rules = ordering.evaluation_order([
            (str(rule.id), rule.sort_field, ordering.attribute_names(rule.outcomes))
            for rule in view.model.objects.only('sort_field', 'outcomes')
        ])
        cache[view.endpoint] = ordering.layout(rules)
    return cache[view.endpoint]


def _render_grouped_outcomes(view, context, model, name):
    """
    The New Attributes column, plus what the list needs to group the rule
    by its attributes and to show where it stands in the evaluation order.
    """
    positions, gaps, tied = _order_info(view)
    rule_id = str(model.id)
    names = ordering.group_names(ordering.attribute_names(model.outcomes))
    marker = (
        f'<span class="ca-order" hidden'
        f' data-rule="{escape(rule_id)}"'
        f' data-name="{escape(model.name)}"'
        f' data-pos="{positions.get(rule_id, 0)}"'
        f' data-tied="{"1" if rule_id in tied else ""}"'
        f' data-attrs="{escape(json.dumps(names))}"'
        f' data-gap="{gaps.get(rule_id, 0)}"'
        f'></span>'
    )
    return Markup(marker) + _render_attribute_outcomes(view, context, model, name)


def _rename_problem(rule, from_attrs, to_attrs):
    """
    Why ``rule`` can not move from the group ``from_attrs`` into the group
    ``to_attrs`` by setting the target group's attribute instead of its own.
    Only a rule with one attribute moves into a group of one attribute, a
    box of several attributes is never changed by a move.
    """
    names = ordering.group_names(ordering.attribute_names(rule.outcomes))
    if names != from_attrs:
        return 'The rule no longer sets these attributes, reload the list'
    if not names or not to_attrs:
        return 'A rule without attribute can not change its group'
    if len(names) > 1 or len(to_attrs) > 1:
        return ('A rule moves into another group only when both set a single '
                'attribute. To change the attributes of a rule with several '
                'attributes, edit the rule')
    return None


def _attrs_param(data, key):
    """A group from the request: a list of attribute names, sorted."""
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return ordering.group_names(value)


class CustomAttributeView(RuleModelView):
    """
    Custom Attribute Model View
    """
    jinja_help_fields = ('attribute_value',)

    list_template = 'admin/custom_attribute_list.html'

    column_formatters = dict(RuleModelView.column_formatters,
                             render_attribute_outcomes=_render_grouped_outcomes)

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'attribute_name': StringField,
                            'attribute_value': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    @expose('/reorder', methods=('POST',))
    def reorder_view(self):
        """
        Drag and drop in the grouped list: put a rule behind (or in front of)
        another one, and with a move into another group of one attribute let
        the rule (of one attribute) set that group's attribute instead.
        """
        if is_readonly(current_user):
            return jsonify(error='Read-only users can not change rules'), 403
        data = request.get_json(silent=True) or {}
        rule_id = str(data.get('rule_id') or '')
        from_attrs = _attrs_param(data, 'from_attrs')
        to_attrs = _attrs_param(data, 'to_attrs')
        if from_attrs is None or to_attrs is None:
            return jsonify(error='No group given'), 400

        rule = self.model.objects(id=rule_id).first() if rule_id else None
        if not rule:
            return jsonify(error='Unknown rule'), 404

        rename = from_attrs != to_attrs
        problem = _rename_problem(rule, from_attrs, to_attrs) if rename else None
        if problem:
            return jsonify(error=problem), 400

        rules = ordering.evaluation_order(
            [(str(entry.id), entry.sort_field) for entry in self.model.objects.only('sort_field')])
        try:
            changes = ordering.move(rules, rule_id,
                                    after_id=data.get('after_id') or None,
                                    before_id=data.get('before_id') or None)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        if rename:
            for outcome in rule.outcomes:
                if outcome.attribute_name == from_attrs[0]:
                    outcome.attribute_name = to_attrs[0]
            rule.save()
        for changed_id, value in changes.items():
            self.model.objects(id=changed_id).update_one(set__sort_field=value)

        if rename or changes:
            add_changes()
            invalidate_host_rule_caches()
        return jsonify(ok=True, renamed=rename, sort_changes=changes)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('global_attributes')
