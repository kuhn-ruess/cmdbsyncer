"""
List Source of a Checkmk Setup Rule

The parts of a list rule (see ``application.modules.rule.list_source``)
only a Setup Rule has: the outcome fields rendered per row and the join of
rows that only differ in their service name.
"""

# Outcome fields of a Setup Rule that are rendered per row, with the label
# used in messages.
OUTCOME_TEMPLATE_FIELDS = (
    ('value_template', 'Value'),
    ('folder', 'Folder'),
    ('list_to_loop', 'Loop over List'),
    ('condition_host', 'Condition Host name'),
    ('condition_label_template', 'Condition Host label'),
    ('condition_service', 'Condition Service name'),
    ('condition_service_label', 'Condition Service label'),
)


def merge_service_conditions(rules):
    """
    Join the rules a list generated for one ruleset that only differ in
    their service name condition into a single rule matching all of those
    services.

    A list gives every row its own rule, but most rows share a value: a
    hundred services in four service levels need four Checkmk rules, not a
    hundred. Two rules are joined when everything except the service
    names is identical (folder, value, comment, description and every
    other condition). The joined rule keeps the position of the first row
    it contains, and the service names keep their row order.
    """
    merged = []
    by_key = {}
    for rule in rules:
        service = rule.get('condition', {}).get('service_description')
        if not service or service.get('operator') != 'one_of':
            merged.append(rule)
            continue
        condition = {key: value for key, value in rule['condition'].items()
                     if key != 'service_description'}
        key = repr((rule.get('folder'), rule.get('value'), rule.get('comment'),
                    rule.get('description'), sorted(condition.items())))
        target = by_key.get(key)
        if target is None:
            rule['condition']['service_description'] = {
                'match_on': list(service['match_on']),
                'operator': 'one_of',
            }
            by_key[key] = rule
            merged.append(rule)
            continue
        match_on = target['condition']['service_description']['match_on']
        for name in service['match_on']:
            if name not in match_on:
                match_on.append(name)
    return merged
