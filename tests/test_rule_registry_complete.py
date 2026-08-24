"""Every MongoEngine model is either exportable or explicitly excluded.

The rule export is meant to be a complete configuration backup. New
models used to silently miss out on it (site pools, notification rules,
projects, …), so this test walks the source tree and fails as soon as a
``db.Document`` shows up that is neither registered in
``rule_definitions.rules`` nor listed in ``rule_definitions.not_exported``.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring

import ast
import importlib.util
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLICATION = os.path.join(REPO_ROOT, 'application')

_DEFS_PATH = os.path.join(APPLICATION, 'plugins', 'rules', 'rule_definitions.py')
_spec = importlib.util.spec_from_file_location('_rule_definitions', _DEFS_PATH)
rule_definitions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rule_definitions)


def _is_document_base(node):
    """True for ``db.Document`` / ``Document`` in a class base list."""
    if isinstance(node, ast.Attribute):
        return node.attr == 'Document'
    return isinstance(node, ast.Name) and node.id == 'Document'


def _model_classes():
    """Yield ``(class_name, relative_path)`` for every model in application/."""
    for dirpath, _dirs, files in os.walk(APPLICATION):
        for filename in files:
            if not filename.endswith('.py'):
                continue
            full_path = os.path.join(dirpath, filename)
            with open(full_path, encoding='utf-8') as source_file:
                tree = ast.parse(source_file.read(), filename=full_path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if any(_is_document_base(base) for base in node.bases):
                    yield node.name, os.path.relpath(full_path, REPO_ROOT)


class RuleRegistryCompleteTests(unittest.TestCase):

    def test_every_model_is_classified(self):
        exported = {entry[1] for entry in rule_definitions.rules.values()}
        unclassified = {
            f"{name} ({path})"
            for name, path in _model_classes()
            if name not in exported and name not in rule_definitions.not_exported
        }
        self.assertEqual(
            unclassified, set(),
            "Add these models to rule_definitions.rules so they are part of "
            "the export, or to rule_definitions.not_exported with a reason.",
        )

    def test_no_stale_exclusions(self):
        known = {name for name, _path in _model_classes()}
        self.assertEqual(set(rule_definitions.not_exported) - known, set())

    def test_registry_points_at_existing_classes(self):
        known = {name for name, _path in _model_classes()}
        registered = {entry[1] for entry in rule_definitions.rules.values()}
        self.assertEqual(registered - known, set())
