"""
Order of the Global Custom Attributes rules, as the grouped rule list shows
it and changes it by drag and drop.

The rules run in the order of their sort value. The list groups them by the
set of attributes they set (a rule with several attributes forms a group of
that combination), which is only a view: a rule moved in it gets the sort
value its new place needs, and only the rules behind it whose value would
otherwise no longer put them behind it are shifted. No other rule changes.

Plain functions without a database, a rule is given as ``(id, sort value)``
or ``(id, sort value, attribute names)``.
"""


def attribute_names(outcomes):
    """The attribute names a rule sets, in order and each once."""
    names = []
    for outcome in outcomes or []:
        name = outcome.get('attribute_name') if isinstance(outcome, dict) \
            else getattr(outcome, 'attribute_name', None)
        if name and name not in names:
            names.append(name)
    return names


def evaluation_order(rules):
    """
    Sort ``(id, sort value, ...)`` tuples the way the list shows them.

    Rules with the same sort value have no fixed order in the database, the
    id (creation order) decides here so the list is at least stable.
    """
    return sorted(rules, key=lambda rule: (rule[1] or 0, str(rule[0])))


def group_names(names):
    """
    The attributes of a group, sorted, so the order in which a rule defines
    them does not matter. A rule stands in exactly one group: the set of
    attributes it sets (``[]`` for a rule without attribute).
    """
    return sorted(set(names or []))


def layout(rules):
    """
    Where every rule stands, for the grouped list.

    ``rules`` are ``(id, sort value, attribute names)`` in evaluation order.
    Returns ``(positions, gaps, tied)``: the 1 based position of every rule,
    for every rule the number of rules of other groups that run between it
    and the one above it in its group, and the ids that share their sort
    value with another rule.
    """
    positions = {}
    gaps = {}
    last_in_group = {}
    seen_values = {}
    for position, (rule_id, value, names) in enumerate(rules, start=1):
        positions[rule_id] = position
        seen_values.setdefault(value or 0, []).append(rule_id)
        group = tuple(group_names(names))
        previous = last_in_group.get(group)
        gaps[rule_id] = position - previous - 1 if previous else 0
        last_in_group[group] = position
    tied = {rule_id for ids in seen_values.values() if len(ids) > 1
            for rule_id in ids}
    return positions, gaps, tied


def _target_index(rest, after_id, before_id):
    """Index in ``rest`` (the rules without the moved one) to insert at."""
    if after_id is not None:
        if after_id not in rest:
            raise ValueError('unknown rule to move behind')
        return rest.index(after_id) + 1
    if before_id is not None:
        if before_id not in rest:
            raise ValueError('unknown rule to move in front of')
        return rest.index(before_id)
    raise ValueError('no target given')


def move(rules, rule_id, after_id=None, before_id=None):
    """
    Move ``rule_id`` directly behind ``after_id``, or directly in front of
    ``before_id`` when there is no rule above it.

    ``rules`` are ``(id, sort value)`` in evaluation order. Returns the new
    sort values as ``{id: value}``, only for the rules that change. Raises
    ``ValueError`` for an unknown rule or a move without a target.
    """
    values = {rid: value or 0 for rid, value in rules}
    if rule_id not in values:
        raise ValueError('unknown rule')
    current = [rid for rid, _value in rules]
    rest = [rid for rid in current if rid != rule_id]
    index = _target_index(rest, after_id, before_id)

    order = rest[:index] + [rule_id] + rest[index:]
    if order == current:
        return {}

    new = [values[rid] for rid in order]
    own = new[index]
    above = new[index - 1] if index > 0 else None
    below = new[index + 1] if index + 1 < len(new) else None

    if (above is None or above < own) and (below is None or own < below):
        pass  # its value already puts it there
    elif above is None:
        # First rule now: stay at zero or above as long as there is room
        new[index] = below - 1 if below > 0 else below
    elif below is not None and below - above >= 2:
        new[index] = (above + below) // 2
    else:
        new[index] = above + 1

    # Shift the rules behind it until one is behind it on its own again
    for pos in range(index + 1, len(new)):
        if new[pos] > new[pos - 1]:
            break
        new[pos] = new[pos - 1] + 1

    return {rid: value for rid, value in zip(order, new) if value != values[rid]}
