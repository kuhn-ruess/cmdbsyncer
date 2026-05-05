"""
Unit tests for the SHA-256 webhook-token flow on CronGroup.

The DB only ever sees the hash; the plaintext is returned by
`ensure_webhook_token` / `regenerate_webhook_token` for one-shot
display. Legacy plaintext rows must auto-upgrade on first read.

The hash logic lives in module-level helpers in
`application.models.cron` (CronGroup methods are thin wrappers), so
these tests can drive a plain stub object without dragging the full
MongoEngine `Document` machinery into the test process.
"""
# pylint: disable=missing-class-docstring,missing-function-docstring
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock

# tests/__init__.py stubs `application` but not `cron_register` —
# add it before loading the cron source so `from application import
# db, cron_register` works.
sys.modules['application'].cron_register = MagicMock(name='stub.cron_register')


def _load_cron_module():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(repo_root, 'application', 'models', 'cron.py')
    spec = importlib.util.spec_from_file_location(
        'application.models.cron', file_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_cron = _load_cron_module()


class _StubGroup:  # pylint: disable=too-few-public-methods
    """Plain attribute-bag stand-in for a CronGroup row."""

    def __init__(self, **kwargs):
        self.webhook_enabled = kwargs.get('webhook_enabled', False)
        self.webhook_token = kwargs.get('webhook_token')
        self.webhook_token_hash = kwargs.get('webhook_token_hash')


class WebhookTokenHashTest(unittest.TestCase):

    def test_ensure_returns_plaintext_and_stores_only_hash(self):
        group = _StubGroup(webhook_enabled=True)
        plaintext = _cron.ensure_webhook_token(group)
        self.assertIsNotNone(plaintext)
        self.assertGreaterEqual(len(plaintext), 32)
        self.assertIsNone(group.webhook_token)
        self.assertEqual(
            group.webhook_token_hash,
            _cron._hash_webhook_token(plaintext),  # pylint: disable=protected-access
        )

    def test_ensure_is_idempotent(self):
        group = _StubGroup(webhook_enabled=True)
        first = _cron.ensure_webhook_token(group)
        existing_hash = group.webhook_token_hash
        second = _cron.ensure_webhook_token(group)
        self.assertIsNone(second)
        self.assertEqual(group.webhook_token_hash, existing_hash)
        self.assertNotEqual(first, '')

    def test_ensure_skips_when_disabled(self):
        group = _StubGroup(webhook_enabled=False)
        self.assertIsNone(_cron.ensure_webhook_token(group))
        self.assertIsNone(group.webhook_token_hash)

    def test_regenerate_replaces_hash_and_returns_new_plaintext(self):
        group = _StubGroup(webhook_enabled=True)
        first = _cron.ensure_webhook_token(group)
        old_hash = group.webhook_token_hash
        new_plaintext = _cron.regenerate_webhook_token(group)
        self.assertNotEqual(new_plaintext, first)
        self.assertNotEqual(group.webhook_token_hash, old_hash)
        self.assertTrue(_cron.verify_webhook_token(group, new_plaintext))
        self.assertFalse(_cron.verify_webhook_token(group, first))

    def test_verify_rejects_wrong_token(self):
        group = _StubGroup(webhook_enabled=True)
        plaintext = _cron.ensure_webhook_token(group)
        self.assertTrue(_cron.verify_webhook_token(group, plaintext))
        self.assertFalse(_cron.verify_webhook_token(group, 'wrong'))
        self.assertFalse(_cron.verify_webhook_token(group, ''))
        self.assertFalse(_cron.verify_webhook_token(group, None))

    def test_verify_returns_false_when_hash_missing(self):
        group = _StubGroup(webhook_enabled=True)
        self.assertFalse(_cron.verify_webhook_token(group, 'anything'))

    def test_legacy_plaintext_is_migrated_on_first_call(self):
        legacy_plain = 'legacy-plaintext-from-pre-4.1'
        group = _StubGroup(webhook_enabled=True, webhook_token=legacy_plain)
        self.assertTrue(_cron.migrate_legacy_webhook_token(group))
        self.assertIsNone(group.webhook_token)
        self.assertEqual(
            group.webhook_token_hash,
            _cron._hash_webhook_token(legacy_plain),  # pylint: disable=protected-access
        )
        self.assertTrue(_cron.verify_webhook_token(group, legacy_plain))

    def test_migrate_is_noop_when_no_legacy_plaintext(self):
        group = _StubGroup(webhook_enabled=True)
        _cron.ensure_webhook_token(group)
        self.assertFalse(_cron.migrate_legacy_webhook_token(group))

    def test_migrate_is_noop_when_hash_already_present(self):
        # Belt-and-braces: even if a row carries both fields, the hash
        # wins — no overwrite, no destruction of the canonical secret.
        existing_hash = _cron._hash_webhook_token('current')  # pylint: disable=protected-access
        group = _StubGroup(
            webhook_enabled=True,
            webhook_token='stale-plaintext',
            webhook_token_hash=existing_hash,
        )
        self.assertFalse(_cron.migrate_legacy_webhook_token(group))
        self.assertEqual(group.webhook_token_hash, existing_hash)


if __name__ == '__main__':
    unittest.main()
