"""
Unit tests for checkmk rule_passwords module
"""
# pylint: disable=missing-function-docstring,protected-access
import ast
import types
import unittest
from unittest.mock import patch, MagicMock

from application.plugins.checkmk.rule_passwords import (
    rewrite_explicit_passwords,
    preserve_password_macros,
    referenced_password_names,
    password_ident,
)

# The Azure special-agent value the user reported: one explicit_password
# ('secret') plus an explicit_proxy that must be left untouched.
AZURE_VALUE = repr({
    'subscription': 'e602c412-033e-4df7-ac6e-6d1a7942aa71',
    'tenant': 'ef65c7f0-656e-4646-a2fd-3e45d36a39fd',
    'client': '743d3780-7009-4865-a894-506d23edf34f',
    'secret': ('cmk_postprocessed', 'explicit_password',
               ('uuidd3b2cc18-be10-4bfa-85e9-bdc4a27562e0', '******')),
    'authority': 'global_',
    'proxy': ('cmk_postprocessed', 'explicit_proxy',
              'http://134.247.251.203:9092'),
    'services': ['Microsoft_Network_slash_loadBalancers'],
    'config': {},
    'piggyback_vms': 'grouphost',
})


class TestRewriteExplicitPasswords(unittest.TestCase):
    """rewrite_explicit_passwords"""

    def test_converts_explicit_and_keeps_proxy(self):
        new_value, hints = rewrite_explicit_passwords(AZURE_VALUE)
        self.assertEqual(hints, ['secret'])
        parsed = ast.literal_eval(new_value)
        # secret is now a stored_password reference with a cmk_password macro
        self.assertEqual(
            parsed['secret'],
            ('cmk_postprocessed', 'stored_password',
             ('{{ cmk_password("secret") }}', '')))
        # the explicit_proxy is untouched
        self.assertEqual(
            parsed['proxy'],
            ('cmk_postprocessed', 'explicit_proxy',
             'http://134.247.251.203:9092'))
        # unrelated fields survive
        self.assertEqual(parsed['authority'], 'global_')

    def test_no_password_returns_unchanged(self):
        value = "{'foo': 'bar'}"
        new_value, hints = rewrite_explicit_passwords(value)
        self.assertEqual(new_value, value)
        self.assertEqual(hints, [])

    def test_unparseable_returns_unchanged(self):
        value = "{'foo': explicit_password("  # contains the marker, won't parse
        new_value, hints = rewrite_explicit_passwords(value)
        self.assertEqual(new_value, value)
        self.assertEqual(hints, [])

    def test_non_string_returns_unchanged(self):
        new_value, hints = rewrite_explicit_passwords(None)
        self.assertIsNone(new_value)
        self.assertEqual(hints, [])

    def test_nested_password_uses_field_key_hint(self):
        value = repr({'servers': [
            {'name': 'a',
             'token': ('cmk_postprocessed', 'explicit_password',
                       ('uuidX', '******'))},
        ]})
        new_value, hints = rewrite_explicit_passwords(value)
        self.assertEqual(hints, ['token'])
        parsed = ast.literal_eval(new_value)
        self.assertEqual(
            parsed['servers'][0]['token'],
            ('cmk_postprocessed', 'stored_password',
             ('{{ cmk_password("token") }}', '')))

    def test_rewritten_value_is_valid_and_round_trips(self):
        # The rewritten value must stay a parseable Python literal whose macro,
        # once a resolver substitutes the ident, yields a valid stored_password.
        new_value, _ = rewrite_explicit_passwords(AZURE_VALUE)
        resolved = new_value.replace('{{ cmk_password("secret") }}',
                                     'cmdbsyncer_deadbeef')
        parsed = ast.literal_eval(resolved)
        self.assertEqual(
            parsed['secret'],
            ('cmk_postprocessed', 'stored_password',
             ('cmdbsyncer_deadbeef', '')))


class TestPreservePasswordMacros(unittest.TestCase):
    """preserve_password_macros"""

    def test_carries_renamed_macro_when_counts_match(self):
        old = "{'secret': ('x', 'y', ('{{ cmk_password(\"azure-prod\") }}', ''))}"
        new = "{'secret': ('x', 'y', ('{{ cmk_password(\"secret\") }}', ''))}"
        merged = preserve_password_macros(old, new)
        self.assertIn('cmk_password("azure-prod")', merged)
        self.assertNotIn('cmk_password("secret")', merged)

    def test_keeps_new_on_count_mismatch(self):
        old = "{{ cmk_password(\"a\") }} {{ cmk_password(\"b\") }}"
        new = "{{ cmk_password(\"secret\") }}"
        self.assertEqual(preserve_password_macros(old, new), new)

    def test_empty_old_keeps_new(self):
        new = "{{ cmk_password(\"secret\") }}"
        self.assertEqual(preserve_password_macros('', new), new)
        self.assertEqual(preserve_password_macros(None, new), new)


class TestReferencedPasswordNames(unittest.TestCase):
    """referenced_password_names"""

    def test_extracts_names_both_quote_styles(self):
        text = ('{{ cmk_password("azure-prod") }} and '
                "{{ cmk_password('other') }}")
        self.assertEqual(referenced_password_names(text),
                         {'azure-prod', 'other'})

    def test_empty_and_none(self):
        self.assertEqual(referenced_password_names(''), set())
        self.assertEqual(referenced_password_names(None), set())

    def test_no_macro(self):
        self.assertEqual(referenced_password_names("{'k': 'v'}"), set())


class TestPasswordIdent(unittest.TestCase):
    """password_ident resolves against the syncer password store"""

    def _patch_model(self, entry):
        fake_models = types.ModuleType(
            'application.plugins.checkmk.models')
        fake_models.CheckmkPassword = MagicMock()
        fake_models.CheckmkPassword.objects.return_value.first.return_value = entry
        return patch.dict(
            'sys.modules',
            {'application.plugins.checkmk.models': fake_models})

    def test_found_returns_prefixed_id(self):
        entry = MagicMock()
        entry.id = 'abc123'
        with self._patch_model(entry):
            self.assertEqual(password_ident('azure-prod'), 'cmdbsyncer_abc123')

    def test_missing_returns_sentinel(self):
        with self._patch_model(None):
            self.assertEqual(password_ident('nope'), 'cmdbsyncer_missing_nope')


if __name__ == '__main__':
    unittest.main()
