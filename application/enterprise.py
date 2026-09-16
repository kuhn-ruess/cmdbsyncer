"""
Enterprise feature registry.

Populated by `load_package()` from the optional `cmdbsyncer_enterprise` package.
If the package is not installed (or its license check fails), the registry
stays empty and all hooks become no-ops — OSS code continues to work.

The published Docker image ships the package on every install, licensed or
not, so a customer who buys a license only has to drop in `license.jwt`.
An install without one must therefore look exactly like an install without
the package: `load_package()` stays silent when there is no license to
activate, and only reports when a license is there and something went wrong
with it.

`load_package()` must be called explicitly from the app factory *after* the
MongoEngine `db` handle has been created, because the enterprise package
transitively imports `application.models.*`, which depend on
`from application import db`.
"""
import os
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


def license_path():
    """Return the file the enterprise package reads its license from.

    Mirrors the resolution in ``cmdbsyncer_enterprise.license``: the
    ``CMDBSYNCER_LICENSE`` environment variable wins, otherwise
    ``license.jwt`` next to the deployment's ``local_config.py``. Resolved
    here instead of asked of the package, because the question comes up
    exactly when the package cannot be imported. Returns None when neither
    candidate can be determined.
    """
    env_path = os.environ.get('CMDBSYNCER_LICENSE')
    if env_path:
        return env_path
    try:
        spec = importlib.util.find_spec('local_config')
    except (ImportError, ValueError):
        spec = None
    if spec and spec.origin:
        return os.path.join(os.path.dirname(spec.origin), 'license.jwt')
    return None


def license_file_present():
    """True when a license file exists where the package looks for it."""
    path = license_path()
    return bool(path) and os.path.isfile(path)


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
        if not license_file_present():
            # Nothing is wrong here — this install simply has no license,
            # which is the normal state for every Community Edition user of
            # the Docker image. Reporting it would put a line that reads
            # like a failure in front of every start they ever do.
            load_status = 'inactive: no license installed'
            return
        load_status = f'failed: {exp}'
        _report(
            f"package installed but failed to activate "
            f"(features disabled, falling back to Community Edition): {exp}"
        )
