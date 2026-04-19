"""
Enterprise feature registry.

Populated at import time by the optional `cmdbsyncer_enterprise` package.
If the package is not installed (or its license check fails), the registry
stays empty and all hooks become no-ops — OSS code continues to work.
"""
import sys
import importlib.util

_features = set()
_hooks = {}

# Plain stderr to bypass any app logging config — these messages need to be
# visible during container startup regardless of logger setup.
load_status = None


def _report(message):
    """Write enterprise load status to stderr so Docker/container logs see it."""
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


if importlib.util.find_spec('cmdbsyncer_enterprise'):
    try:
        import cmdbsyncer_enterprise  # noqa: F401  pylint: disable=unused-import, import-error
        load_status = 'active'
        _report("package loaded successfully")
    except Exception as exp:  # pylint: disable=broad-exception-caught
        load_status = f'failed: {exp}'
        _report(
            f"package installed but failed to activate "
            f"(features disabled, falling back to Community Edition): {exp}"
        )
