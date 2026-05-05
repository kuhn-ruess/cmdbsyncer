"""
Invariant: every endpoint reachable under /api/v1/* must authenticate
per request via @require_token (or @require_api_role on the rare
non-RESTX route).

This test guards the `csrf.exempt(api)` call in application/__init__.py.
The exempt is *required* because external clients (CLI, MCP server,
Ansible inventory pulls, Grafana scrapes) don't carry a CSRF token —
but it's only safe as long as no /api/v1 route silently relies on
session/cookie auth. A reviewer who removes the exempt without first
auditing every namespace would re-introduce the breakage; equally,
a reviewer who adds a session-auth route under /api/v1 without
@require_token would silently expose it to CSRF.

Implementation: walk the api/*.py source with `ast` and check that
every HTTP-verb method (`get`, `post`, ...) on a Flask-RESTX Resource
subclass carries one of `require_token` / `require_api_role` /
`webhook_auth` (the enterprise hook is itself a require_token-style
verifier) as a direct decorator. Pure static analysis — no module
loader dependency, so it works regardless of the test bootstrap.
"""
import ast
import os
import unittest


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API_DIR = os.path.join(_REPO_ROOT, 'application', 'api')

_HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}

# Decorator names that are accepted as "this method authenticates".
# require_token: Basic-Auth + role-prefix path check (the canonical case).
# require_api_role: explicit role for non-RESTX routes (Prometheus scrape).
# webhook_auth: enterprise webhook signature verifier — itself blocks
# unauthenticated requests, so a route gated solely behind it is safe.
_AUTH_DECORATORS = {'require_token', 'require_api_role', 'webhook_auth'}


def _decorator_name(node):
    """Return the bottom-line name of a decorator AST node, or None."""
    # @require_token -> Name(id='require_token')
    if isinstance(node, ast.Name):
        return node.id
    # @require_api_role('foo') -> Call(func=Name(id='require_api_role'))
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    # @something.attr -> Attribute(attr='attr')
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _calls_auth_inside(func_node):
    """True iff the function body invokes one of the auth helpers
    explicitly (e.g. `require_token(lambda: None)()` — used by the
    webhook trigger which supports three auth modes and can't pin
    one as a decorator)."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            name = _decorator_name(node.func)
            if name in _AUTH_DECORATORS:
                return True
    return False


def _iter_resource_methods(tree):
    """Yield (class_name, func_node) for every HTTP-verb method on a
    class that inherits from Resource (Flask-RESTX) anywhere in the
    parsed AST tree."""
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        # Heuristic: any base named Resource (with or without prefix).
        is_resource = any(
            (isinstance(b, ast.Name) and b.id == 'Resource')
            or (isinstance(b, ast.Attribute) and b.attr == 'Resource')
            for b in cls.bases
        )
        if not is_resource:
            continue
        for stmt in cls.body:
            if isinstance(stmt, ast.FunctionDef) and stmt.name in _HTTP_METHODS:
                yield cls.name, stmt


def _api_source_files():
    return sorted(
        os.path.join(_API_DIR, f) for f in os.listdir(_API_DIR)
        if f.endswith('.py') and f != '__init__.py'
    )


class TestApiCsrfInvariant(unittest.TestCase):
    """Lock in the precondition for `csrf.exempt(api)`."""

    def test_every_resource_method_has_require_token(self):
        """No `/api/v1` route may fall through to session auth."""
        offenders = []
        for path in _api_source_files():
            with open(path, 'r', encoding='utf-8') as fh:
                tree = ast.parse(fh.read(), filename=path)
            for cls_name, func in _iter_resource_methods(tree):
                deco_names = {_decorator_name(d) for d in func.decorator_list}
                if (deco_names & _AUTH_DECORATORS) or _calls_auth_inside(func):
                    continue
                rel = os.path.relpath(path, _REPO_ROOT)
                offenders.append(
                    f"{rel}:{func.lineno} "
                    f"{cls_name}.{func.name}() lacks @require_token / "
                    f"@require_api_role — would expose a CSRF-exempt "
                    f"route to anonymous browser session abuse"
                )
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_at_least_one_resource_was_scanned(self):
        """Sanity guard so the test doesn't trivially pass when the
        api/ layout changes and `_iter_resource_methods` walks
        nothing."""
        scanned = 0
        for path in _api_source_files():
            with open(path, 'r', encoding='utf-8') as fh:
                tree = ast.parse(fh.read(), filename=path)
            scanned += sum(1 for _ in _iter_resource_methods(tree))
        self.assertGreater(scanned, 5)


if __name__ == '__main__':
    unittest.main()
