"""
Index hygiene across every MongoEngine model in the repo.

A compound index already serves any query on its leftmost fields, so a
second index on that prefix is maintained on every write and never
chosen by the planner. The declarations are read straight from the
source with `ast` — the models themselves need a stubbed `application`
package to import, and this invariant is about what is declared, not
about what a particular test run can construct.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import ast
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _model_sources():
    """Every .py file under application/ that declares model indexes."""
    for root, _dirs, files in os.walk(os.path.join(_REPO_ROOT, 'application')):
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.join(root, name)
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
            if "'indexes'" in source or '"indexes"' in source:
                yield os.path.relpath(path, _REPO_ROOT), source


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _index_fields(entry):
    """The field list of one index declaration, or None if not readable."""
    value = _literal(entry)
    if isinstance(value, (list, tuple)):
        return [str(field) for field in value]
    if isinstance(value, dict):
        fields = value.get('fields')
        if isinstance(fields, (list, tuple)):
            return [str(field) for field in fields]
    return None


def _declared_indexes(source):
    """Yield (class_name, [[field, ...], ...]) for each model in `source`."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
            if 'meta' not in targets or not isinstance(item.value, ast.Dict):
                continue
            for key, value in zip(item.value.keys, item.value.values):
                if _literal(key) != 'indexes' or not isinstance(value, ast.List):
                    continue
                indexes = [_index_fields(entry) for entry in value.elts]
                yield node.name, [i for i in indexes if i]


def _normalise(fields):
    """Drop the sort-direction prefix — it does not affect prefix cover."""
    return tuple(field.lstrip('+-') for field in fields)


class ModelIndexTest(unittest.TestCase):

    def test_no_index_is_a_prefix_of_another(self):
        offenders = []
        for path, source in _model_sources():
            for class_name, indexes in _declared_indexes(source):
                keys = [_normalise(fields) for fields in indexes]
                for i, shorter in enumerate(keys):
                    for j, longer in enumerate(keys):
                        if i == j or len(shorter) >= len(longer):
                            continue
                        if longer[:len(shorter)] == shorter:
                            offenders.append(
                                f'{path}:{class_name}: {list(shorter)} is a '
                                f'prefix of {list(longer)}'
                            )
        self.assertEqual(offenders, [], 'redundant index declarations:\n  '
                                        + '\n  '.join(offenders))

    def test_no_index_is_declared_twice(self):
        offenders = []
        for path, source in _model_sources():
            for class_name, indexes in _declared_indexes(source):
                seen = set()
                for fields in indexes:
                    key = _normalise(fields)
                    if key in seen:
                        offenders.append(f'{path}:{class_name}: {list(key)}')
                    seen.add(key)
        self.assertEqual(offenders, [], f'duplicate indexes: {offenders}')

    def test_the_scan_actually_finds_models(self):
        # Guard against the walk silently matching nothing and the two
        # tests above passing for the wrong reason.
        found = [name for _path, source in _model_sources()
                 for name, _idx in _declared_indexes(source)]
        self.assertGreater(len(found), 5, f'only found {found}')


if __name__ == '__main__':
    unittest.main()
