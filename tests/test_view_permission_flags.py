"""
Invariant: no admin view assigns its own ``can_create`` / ``can_edit`` /
``can_delete`` on an instance.

``DefaultModelView`` publishes the three as properties so a read-only user
is kept out of the model layer in one place. A property is a data
descriptor, so ``self.can_edit = False`` inside a view's ``__init__``
raises ``AttributeError: property 'can_edit' of '...' object has no
setter`` — and because the views are built while the Flask app is
constructed, that takes the whole web app down at startup instead of
failing on a single page.

A view that wants a flag off under some condition overrides it with a
property of its own (see ``HostModelView``), which this test allows.
"""

import ast
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARDED = frozenset({'can_create', 'can_edit', 'can_delete'})


def _python_files():
    """Every application source file, tests and vendored trees aside."""
    for root, dirs, files in os.walk(os.path.join(REPO_ROOT, 'application')):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'static')]
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


def _self_assignments(tree):
    """``self.<flag> = ...`` targets found anywhere in the tree."""
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and target.attr in GUARDED
                    and isinstance(target.value, ast.Name)
                    and target.value.id == 'self'):
                yield target.attr, node.lineno


class TestViewPermissionFlags(unittest.TestCase):
    """Guard the read-only property contract of DefaultModelView."""

    def test_no_instance_assignment_of_permission_flags(self):
        """An assignment here would raise on app startup."""
        offenders = []
        for path in _python_files():
            with open(path, 'r', encoding='utf-8') as source:
                tree = ast.parse(source.read(), filename=path)
            for attr, lineno in _self_assignments(tree):
                relative = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{relative}:{lineno}: self.{attr} = ...")
        self.assertEqual(
            offenders, [],
            "Views must override can_create/can_edit/can_delete with a "
            "property, not assign them on the instance:\n  "
            + "\n  ".join(offenders))


if __name__ == '__main__':
    unittest.main()
