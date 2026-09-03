"""
Enterprise feature registry.

Populated by `load_package()` from the optional `cmdbsyncer_enterprise` package.
If the package is not installed (or its license check fails), the registry
stays empty and all hooks become no-ops — OSS code continues to work.

`load_package()` must be called explicitly from the app factory *after* the
MongoEngine `db` handle has been created, because the enterprise package
transitively imports `application.models.*`, which depend on
`from application import db`.
"""
import sys
import importlib.util

_features = set()
_hooks = {}

load_status = None  # pylint: disable=invalid-name
_pending_report = None  # pylint: disable=invalid-name


def _report(message):
    """Hold the load status until there is somewhere good to put it.

    ``load_package()`` runs before the log pipeline is configured — it
    has to, the pipeline itself is one of the things a license unlocks —
    so writing here would always produce a plain line, whatever the
    deployment asked for. ``emit_load_status()`` writes it afterwards.
    """
    # ``./cmdbsyncer <command>`` sets CMDBSYNCER_CLI so command output isn't
    # preceded by a banner line — the web/worker processes keep the banner.
    import os  # pylint: disable=import-outside-toplevel
    if os.environ.get("CMDBSYNCER_CLI") == "1":
        return
    global _pending_report  # pylint: disable=global-statement
    _pending_report = message


def emit_load_status(logger=None):
    """Write the held status line, once.

    With a `logger` the line becomes an ordinary record, so a deployment
    collecting structured logs gets it in the shape it configured.
    Without one it goes to stderr, where it stays visible even on an
    install whose logging is not set up at all — which is exactly the
    install most likely to be asking whether the package loaded.
    """
    global _pending_report  # pylint: disable=global-statement
    if _pending_report is None:
        return
    message, _pending_report = _pending_report, None
    if logger is not None:
        logger.info(message, extra={'event_source': 'enterprise'})
    else:
        print(f"[cmdbsyncer-enterprise] {message}", file=sys.stderr, flush=True)


def register_feature(name, hook_fn=None):
    """Enable a named feature and optionally bind an implementation function."""
    _features.add(name)
    if hook_fn is not None:
        _hooks[name] = hook_fn


def has_feature(name):
    """Return True if the named feature has been registered."""
    return name in _features


def run_hook(name, *args, **kwargs):
    """Invoke a registered hook by name. Returns None if no hook is bound."""
    fn = _hooks.get(name)
    return fn(*args, **kwargs) if fn else None


def load_package():
    """Import the enterprise package if present. Safe to call multiple times."""
    global load_status  # pylint: disable=global-statement
    if load_status is not None:
        return
    if not importlib.util.find_spec('cmdbsyncer_enterprise'):
        return
    try:
        import cmdbsyncer_enterprise  # noqa: F401  pylint: disable=unused-import, import-error, import-outside-toplevel
        load_status = 'active'
        _report("package loaded successfully")
    except Exception as exp:  # pylint: disable=broad-exception-caught
        load_status = f'failed: {exp}'
        _report(
            f"package installed but failed to activate "
            f"(features disabled, falling back to Community Edition): {exp}"
        )
