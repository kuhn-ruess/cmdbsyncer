"""
The Global Custom Attributes list groups the rules by the attribute set
(every rule in exactly one group) and changes their order by drag and
drop. Grouping is only a view, a move gives the moved rule the sort value
its new place needs and shifts only the rules behind it that would
otherwise no longer run behind it.
"""
# pylint: disable=missing-function-docstring
import importlib.util
import os
import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'application', 'modules', 'custom_attributes', 'ordering.py')
_SPEC = importlib.util.spec_from_file_location('custom_attribute_ordering', _PATH)
ordering = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ordering)


class TestMove(unittest.TestCase):
    """ordering.move"""

    RULES = [('a', 10), ('b', 20), ('c', 30), ('d', 40)]

    def test_into_a_gap_changes_only_the_moved_rule(self):
        self.assertEqual(ordering.move(self.RULES, 'd', after_id='a'), {'d': 15})

    def test_own_value_kept_when_it_already_fits(self):
        rules = [('a', 10), ('b', 20), ('c', 30)]
        self.assertEqual(ordering.move(rules, 'b', after_id='a'), {})

    def test_to_the_top(self):
        self.assertEqual(ordering.move(self.RULES, 'c', before_id='a'), {'c': 9})

    def test_to_the_end(self):
        self.assertEqual(ordering.move(self.RULES, 'a', after_id='d'), {'a': 41})

    def test_no_gap_shifts_the_rules_behind(self):
        rules = [('a', 1), ('b', 2), ('c', 3), ('d', 10)]
        self.assertEqual(ordering.move(rules, 'd', after_id='a'),
                         {'d': 2, 'b': 3, 'c': 4})

    def test_default_values_get_an_order(self):
        rules = [('a', 0), ('b', 0), ('c', 0)]
        self.assertEqual(ordering.move(rules, 'c', before_id='a'),
                         {'a': 1, 'b': 2})

    def test_ties_in_front_stay_untouched(self):
        rules = [('a', 0), ('b', 0), ('c', 5), ('d', 9)]
        self.assertEqual(ordering.move(rules, 'b', after_id='c'), {'b': 7})

    def test_unchanged_place(self):
        self.assertEqual(ordering.move(self.RULES, 'b', after_id='a'), {})

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            ordering.move(self.RULES, 'x', after_id='a')
        with self.assertRaises(ValueError):
            ordering.move(self.RULES, 'a', after_id='a')
        with self.assertRaises(ValueError):
            ordering.move(self.RULES, 'a')

    def test_result_is_the_requested_order(self):
        rules = [('a', 0), ('b', 3), ('c', 3), ('d', 4), ('e', 4)]
        for rule_id, after in (('e', 'a'), ('a', 'c'), ('d', 'b'), ('b', 'e')):
            changes = ordering.move(rules, rule_id, after_id=after)
            values = {rid: changes.get(rid, value) for rid, value in rules}
            order = [rid for rid, _ in sorted(values.items(), key=lambda i: i[1])]
            self.assertLess(order.index(after), order.index(rule_id))
            self.assertEqual(order.index(rule_id), order.index(after) + 1)


class TestLayout(unittest.TestCase):
    """ordering.layout and its helpers"""

    def test_positions_gaps_and_ties(self):
        rules = ordering.evaluation_order([
            ('r3', 20, ['site']), ('r1', 10, ['site']),
            ('r2', 10, ['owner']), ('r4', 30, []),
        ])
        self.assertEqual([rule[0] for rule in rules], ['r1', 'r2', 'r3', 'r4'])
        positions, gaps, tied = ordering.layout(rules)
        self.assertEqual(positions, {'r1': 1, 'r2': 2, 'r3': 3, 'r4': 4})
        self.assertEqual(gaps, {'r1': 0, 'r2': 0, 'r3': 1, 'r4': 0})
        self.assertEqual(tied, {'r1', 'r2'})

    def test_several_attributes_form_their_own_group(self):
        rules = [('r1', 10, ['site', 'owner']), ('r2', 20, ['site']),
                 ('r3', 30, ['owner', 'site']), ('r4', 40, ['owner'])]
        _positions, gaps, _tied = ordering.layout(rules)
        # r3 sets the same set as r1 in another order: one group, r2 between
        self.assertEqual(gaps, {'r1': 0, 'r2': 0, 'r3': 1, 'r4': 0})

    def test_group_names(self):
        self.assertEqual(ordering.group_names(['site', 'owner']), ['owner', 'site'])
        self.assertEqual(ordering.group_names(['owner', 'site']), ['owner', 'site'])
        self.assertEqual(ordering.group_names([]), [])

    def test_attribute_names(self):
        self.assertEqual(ordering.attribute_names(
            [{'attribute_name': 'a'}, {'attribute_name': ''},
             {'attribute_name': 'a'}, {'attribute_name': 'b'}]), ['a', 'b'])


REORDER = LOGIN + '''
from application.modules.custom_attributes.models import CustomAttributeRule
from application.modules.rule.models import CustomAttribute

def rule(name, sort, *attrs):
    entry = CustomAttributeRule(
        name=name, enabled=True, condition_typ='anyway', sort_field=sort,
        outcomes=[CustomAttribute(attribute_name=a, attribute_value='x') for a in attrs])
    entry.save()
    return str(entry.id)

one = rule('rule-one', 10, 'site')
two = rule('rule-two', 20, 'owner')
three = rule('rule-three', 30, 'site', 'owner')

listing = check('/admin/customattributerule/', 200).get_data(as_text=True)
for needle in ('class="ca-order"', '/admin/customattributerule/reorder'):
    if needle not in listing:
        fail(f'the list does not contain {needle!r}')
if f'data-rule="{three}"' not in listing:
    fail('the list does not mark the rules for grouping')

token = csrf('/admin/customattributerule/new/')
url = '/admin/customattributerule/reorder'

def move(status, rule_id, from_attrs, to_attrs, **target):
    payload = dict(target, rule_id=rule_id, from_attrs=from_attrs, to_attrs=to_attrs)
    check(url, status, method='post', headers={'X-CSRFToken': token}, json=payload)

# A move within the group: rule-three in front of rule-one (order only)
move(200, three, ['owner', 'site'], ['owner', 'site'], before_id=one)
eq(CustomAttributeRule.objects(id=three).first().sort_field, 9, 'moved sort value')
eq(CustomAttributeRule.objects(id=one).first().sort_field, 10, 'untouched rule')

# Into another group: rule-one now sets owner instead of site
move(200, one, ['site'], ['owner'], after_id=two)
moved = CustomAttributeRule.objects(id=one).first()
eq([o.attribute_name for o in moved.outcomes], ['owner'], 'renamed attribute')
eq(moved.sort_field, 21, 'sort value behind rule-two')

# Out of and into a box of several attributes is refused, nothing changes
move(400, three, ['owner', 'site'], ['owner'], after_id=two)
move(400, two, ['owner'], ['owner', 'site'], after_id=three)
eq([o.attribute_name for o in CustomAttributeRule.objects(id=three).first().outcomes],
   ['site', 'owner'], 'refused rule unchanged')
eq(CustomAttributeRule.objects(id=three).first().sort_field, 9, 'refused rule kept its place')
eq([o.attribute_name for o in CustomAttributeRule.objects(id=two).first().outcomes],
   ['owner'], 'refused target rule unchanged')
eq(CustomAttributeRule.objects(id=two).first().sort_field, 20, 'refused rule kept its place')

# A stale group (the rule no longer sets these attributes) is refused
move(400, two, ['site'], ['owner'], after_id=one)

# No CSRF token, no change
check(url, 400, method='post',
      json={'rule_id': two, 'before_id': three,
            'from_attrs': ['owner'], 'to_attrs': ['owner']})
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestReorderEndpoint(unittest.TestCase):
    """The reorder endpoint against the real app"""

    def test_reorder(self):
        result = run_against_app(REORDER, 'False')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
