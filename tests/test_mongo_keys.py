"""
Unit tests for the centralized MongoDB key validator used by the Host
model, API handlers, and plugins.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import unittest


def _load_mongo_keys():
    # tests/__init__.py stubs `application.helpers` as an empty package, so
    # the real module has to be loaded explicitly.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, 'application', 'helpers', 'mongo_keys.py')
    spec = importlib.util.spec_from_file_location(
        'application.helpers.mongo_keys', path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['application.helpers.mongo_keys'] = module
    spec.loader.exec_module(module)
    return module


_MK = _load_mongo_keys()
validate_mongo_key = _MK.validate_mongo_key
validate_mongo_keys = _MK.validate_mongo_keys


class ValidateMongoKeyTest(unittest.TestCase):

    def test_accepts_plain_key(self):
        # No exception means "valid".
        validate_mongo_key('cpu', 'inventory')

    def test_rejects_empty_string(self):
        with self.assertRaises(ValueError):
            validate_mongo_key('', 'inventory')

    def test_rejects_non_string(self):
        with self.assertRaises(ValueError):
            validate_mongo_key(42, 'inventory')

    def test_rejects_dollar_prefix(self):
        with self.assertRaises(ValueError):
            validate_mongo_key('$set', 'inventory')

    def test_rejects_dot_in_key(self):
        with self.assertRaises(ValueError):
            validate_mongo_key('a.b', 'inventory')

    def test_allows_dollar_not_at_start(self):
        # MongoDB only disallows `$` at position 0.
        validate_mongo_key('foo$bar', 'label')


class ValidateMongoKeysTest(unittest.TestCase):

    def test_silently_ignores_non_dict(self):
        # Non-dict mapping (e.g. None) must be a no-op: callers already
        # pass dict-or-None unconditionally.
        validate_mongo_keys(None, 'label')
        validate_mongo_keys([], 'label')

    def test_accepts_all_valid(self):
        validate_mongo_keys({'a': 1, 'b': 2}, 'label')

    def test_first_bad_key_raises(self):
        with self.assertRaises(ValueError):
            validate_mongo_keys({'ok': 1, '$bad': 2}, 'label')


if __name__ == '__main__':
    unittest.main()
