"""
Jira Cloud Export Rule
"""
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja


class JiraExportAttributeRule(Rule):
    """
    Resolves the per-host outcome of one or more JiraExportRule rows.

    All enabled rules are loaded into a single engine instance so the
    export plugin can iterate hosts once and let the engine merge every
    matching rule's outcomes per host.  Outcomes are grouped by Jira
    object type id; missing objects are always created (filter out
    hosts you don't want exported via a JiraCloudFilterRule).
    """
    name = "Jira Cloud -> Export Attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Build per-type field bundles.

        Output shape::

            outcomes['fields_by_type'] = {
                "<type_id>": {"<attr_name>": "<rendered_value>", ...},
                ...
            }

        Mongo DictFields require string keys, so ``object_type_id`` is
        stored as a string and converted back to int by the consumer.
        Empty/None-rendered values are dropped so an unset host attribute
        does not blank out a populated field in Jira.
        """
        outcomes.setdefault('fields_by_type', {})
        for outcome in rule_outcomes:
            target = (outcome.get('target') or '').strip()
            if '|' not in target:
                continue
            type_id_str, attr = target.split('|', 1)
            attr = attr.strip()
            if not type_id_str or not attr:
                continue
            template = outcome.get('value') or ''
            rendered = render_jinja(template, mode="nullify", **self.attributes)
            rendered = (rendered or '').strip()
            if rendered in ('', 'None'):
                continue
            outcomes['fields_by_type'].setdefault(type_id_str, {})[attr] = rendered
        return outcomes
