"""Tests for the Lucene-flavoured host search parser."""
# pylint: disable=missing-function-docstring,missing-class-docstring,too-many-public-methods

import importlib.util
import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import the parser module directly without going through tests/__init__'s
# stubbed `application` package — the parser is pure-Python and has no
# Mongo / Flask dependencies, so the heavy stubbing isn't needed here.
_PARSER_PATH = os.path.join(
    REPO_ROOT, 'application', 'modules', 'search_parser.py'
)
_spec = importlib.util.spec_from_file_location(
    'search_parser_under_test', _PARSER_PATH,
)
search_parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(search_parser)
parse_search = search_parser.parse_search
SearchSyntaxError = search_parser.SearchSyntaxError


class ParseSearchTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(parse_search(''))
        self.assertIsNone(parse_search('   '))
        self.assertIsNone(parse_search(None))

    def test_bare_term_matches_hostname_labels_inventory_keys_and_values(self):
        # Bare term matches hostname + label key + label value +
        # inventory key + inventory value — five clauses total.
        # The key-side clauses are what makes `NOT foo` mean "no label
        # named foo" instead of "no value containing foo".
        result = parse_search('prod')
        self.assertIn('$or', result)
        clauses = result['$or']
        self.assertEqual(len(clauses), 5)
        self.assertEqual(clauses[0], {'hostname': {'$regex': 'prod', '$options': 'i'}})
        # Remaining four are $expr label/inventory matches (key & value)
        for clause in clauses[1:]:
            self.assertIn('$expr', clause)

    def test_bare_term_matches_label_key_name(self):
        # The $expr clauses must reference both `$$kv.k` (key) and
        # `$$kv.v` (value) for labels and inventory.
        result = parse_search('basti_test')
        body = repr(result)
        self.assertIn('$$kv.k', body)
        self.assertIn('$$kv.v', body)

    def test_bare_term_key_match_is_anchored(self):
        # Keys are anchored (^...$) so `basti_test` does NOT match a
        # label named `basti_test2` — only an exact key match. Values
        # stay unanchored so substring searches keep working.
        result = parse_search('basti_test')
        body = repr(result)
        # The key clauses use the anchored regex
        self.assertIn("'regex': '^(?:basti_test)$'", body)
        # The value clauses keep the unanchored regex
        self.assertIn("'regex': 'basti_test'", body)

    def test_wildcard_in_bare_term_expands_anchored_key_regex(self):
        # `basti_test*` should match keys starting with `basti_test`
        # (including `basti_test2`). The anchored regex becomes
        # `^basti_test.*$` after wildcard expansion.
        result = parse_search('basti_test*')
        body = repr(result)
        self.assertIn("'regex': '^(?:basti_test.*)$'", body)

    def test_hostname_field_targets_only_hostname(self):
        result = parse_search('hostname:web')
        self.assertEqual(result, {'hostname': {'$regex': 'web', '$options': 'i'}})

    def test_arbitrary_field_targets_labels_and_inventory(self):
        result = parse_search('env:prod')
        self.assertEqual(result, {'$or': [
            {'labels.env': {'$regex': 'prod', '$options': 'i'}},
            {'inventory.env': {'$regex': 'prod', '$options': 'i'}},
        ]})

    def test_explicit_labels_dot_routes_only_to_labels(self):
        result = parse_search('labels.env:prod')
        self.assertEqual(result, {'labels.env': {'$regex': 'prod', '$options': 'i'}})

    def test_explicit_inventory_dot_routes_only_to_inventory(self):
        result = parse_search('inventory.cpu:8')
        self.assertEqual(result, {'inventory.cpu': {'$regex': '8', '$options': 'i'}})

    def test_implicit_and_between_terms(self):
        result = parse_search('prod web')
        self.assertEqual(set(result.keys()), {'$and'})
        self.assertEqual(len(result['$and']), 2)

    def test_explicit_and_keyword(self):
        result_implicit = parse_search('prod web')
        result_explicit = parse_search('prod AND web')
        self.assertEqual(result_implicit, result_explicit)

    def test_or_keyword(self):
        result = parse_search('prod OR stage')
        self.assertEqual(set(result.keys()), {'$or'})
        self.assertEqual(len(result['$or']), 2)

    def test_not_keyword(self):
        result = parse_search('NOT archived')
        self.assertEqual(set(result.keys()), {'$nor'})
        self.assertEqual(len(result['$nor']), 1)

    def test_bang_negation(self):
        # `!` is an alternative spelling for NOT
        a = parse_search('!archived')
        b = parse_search('NOT archived')
        self.assertEqual(a, b)

    def test_keywords_are_case_insensitive(self):
        a = parse_search('prod and web')
        b = parse_search('prod AND web')
        c = parse_search('prod And web')
        self.assertEqual(a, b)
        self.assertEqual(b, c)

    def test_parentheses_group_precedence(self):
        # `(prod OR stage) AND NOT test` — without parens, AND would bind
        # tighter and the OR would lose its right-hand term.
        result = parse_search('(prod OR stage) AND NOT test')
        self.assertIn('$and', result)
        self.assertEqual(len(result['$and']), 2)
        self.assertEqual(set(result['$and'][0].keys()), {'$or'})
        self.assertEqual(set(result['$and'][1].keys()), {'$nor'})

    def test_quoted_value_preserves_spaces_and_escapes(self):
        result = parse_search('hostname:"foo bar"')
        # quoted -> literal regex via re.escape
        self.assertEqual(result, {'hostname': {'$regex': r'foo\ bar', '$options': 'i'}})

    def test_quoted_star_is_literal(self):
        result = parse_search('hostname:"web*"')
        # `*` inside quotes must NOT be turned into `.*`
        self.assertEqual(result, {'hostname': {'$regex': r'web\*', '$options': 'i'}})

    def test_unquoted_star_becomes_wildcard(self):
        result = parse_search('hostname:web*')
        self.assertEqual(result, {'hostname': {'$regex': 'web.*', '$options': 'i'}})

    def test_unquoted_question_mark_becomes_dot(self):
        result = parse_search('hostname:web?')
        self.assertEqual(result, {'hostname': {'$regex': 'web.', '$options': 'i'}})

    def test_bad_regex_falls_back_to_escape(self):
        # A bare `[` would fail re.compile; the parser must not raise
        # for it — fall back to literal escape so the user still gets a
        # result instead of a crash.
        result = parse_search('hostname:[unbalanced')
        self.assertEqual(result['hostname']['$regex'], r'\[unbalanced')

    def test_unterminated_quote_raises(self):
        with self.assertRaises(SearchSyntaxError):
            parse_search('hostname:"foo')

    def test_unmatched_paren_raises(self):
        with self.assertRaises(SearchSyntaxError):
            parse_search('(prod OR stage')

    def test_dangling_operator_raises(self):
        with self.assertRaises(SearchSyntaxError):
            parse_search('prod AND')

    def test_field_with_no_value_raises(self):
        with self.assertRaises(SearchSyntaxError):
            parse_search('hostname:')

    def test_complex_expression_round_trip(self):
        # End-to-end smoke test of the example from the picker
        result = parse_search('(prod OR stage) AND NOT test')
        self.assertIsNotNone(result)
        # And the equivalent symbol-only form
        result2 = parse_search('(prod OR stage) !test')
        # Both should produce an AND with an OR + a NOR child
        for r in (result, result2):
            self.assertIn('$and', r)
            kinds = sorted(list(c.keys())[0] for c in r['$and'])
            self.assertEqual(kinds, ['$nor', '$or'])


class ShortFieldFormTests(unittest.TestCase):
    """`h:` / `l.x:` / `i.x:` are short forms of the long field names."""

    def test_h_is_hostname(self):
        self.assertEqual(parse_search('h:web'), parse_search('hostname:web'))
        self.assertEqual(parse_search('host:web'), parse_search('hostname:web'))

    def test_short_form_is_case_insensitive(self):
        self.assertEqual(parse_search('H:web'), parse_search('hostname:web'))

    def test_label_and_inventory_prefix(self):
        self.assertEqual(parse_search('l.env:prod'),
                         parse_search('labels.env:prod'))
        self.assertEqual(parse_search('i.cpu:8'),
                         parse_search('inventory.cpu:8'))

    def test_label_key_keeps_its_case(self):
        result = parse_search('l.Env:prod')
        self.assertEqual(result, {'labels.Env': {'$regex': 'prod', '$options': 'i'}})

    def test_unknown_field_untouched(self):
        # `hoster` must not be mistaken for the `h` short form
        result = parse_search('hoster:x')
        self.assertEqual(result, {'$or': [
            {'labels.hoster': {'$regex': 'x', '$options': 'i'}},
            {'inventory.hoster': {'$regex': 'x', '$options': 'i'}},
        ]})


class RegexValueTests(unittest.TestCase):
    """A value between slashes is used as a regex, without globbing."""

    def test_regex_value_is_used_as_typed(self):
        result = parse_search(r'h:/^web\d+$/')
        self.assertEqual(result,
                         {'hostname': {'$regex': r'^web\d+$', '$options': 'i'}})

    def test_star_is_not_translated_in_regex(self):
        # `web[0-9]*` must stay a regex quantifier, not become `.*`
        result = parse_search('h:/web[0-9]*/')
        self.assertEqual(result['hostname']['$regex'], 'web[0-9]*')

    def test_regex_may_contain_parens_and_pipes(self):
        result = parse_search('h:/^(web|db)[0-9]+/')
        self.assertEqual(result['hostname']['$regex'], '^(web|db)[0-9]+')

    def test_bare_regex_searches_every_field(self):
        result = parse_search('/^web[0-9]+$/')
        self.assertEqual(len(result['$or']), 5)
        self.assertEqual(result['$or'][0],
                         {'hostname': {'$regex': '^web[0-9]+$', '$options': 'i'}})

    def test_regex_key_match_stays_anchored_as_a_group(self):
        # An alternation must not swallow the key anchors
        body = repr(parse_search('/web|db/'))
        self.assertIn("'regex': '^(?:web|db)$'", body)

    def test_regex_combines_with_operators(self):
        result = parse_search('h:/^web/ AND env:prod')
        self.assertIn('$and', result)
        self.assertEqual(len(result['$and']), 2)

    def test_invalid_regex_raises(self):
        # Unlike a plain term, an explicit regex reports the typo
        with self.assertRaises(SearchSyntaxError):
            parse_search('h:/[unbalanced/')

    def test_path_like_word_is_no_regex(self):
        # `/srv/data` and `srv/data` stay ordinary terms
        result = parse_search('hostname:srv/data')
        self.assertEqual(result['hostname']['$regex'], 'srv/data')
        self.assertEqual(parse_search('hostname:/srv/data')['hostname']['$regex'],
                         '/srv/data')


if __name__ == '__main__':
    unittest.main()
