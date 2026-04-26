"""Plugin discovery and enable/disable helpers.

A plugin is enabled by default when its directory ships under
``application/plugins/`` or ``plugins/``. The only opt-out is
``disabled_plugins.json`` at the repo root, which holds a JSON list of
disabled idents (or directory names — both work).

Both the disabled list and the per-plugin ``plugin.json`` data are read
exactly once per process and cached. The filesystem state cannot change
under us during a single Flask/CLI run; if a plugin is added or
disabled, restart the process (or call ``set_disabled_plugins`` from
the same process — it busts its own cache).
"""
import os
import json

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DISABLED_PLUGINS_PATH = os.path.join(_BASE_DIR, 'disabled_plugins.json')

# In-memory registry for plugin types that ship inside a pip-installed
# Enterprise package rather than as a directory under plugins/. Callers
# use register_plugin_type(...) at feature activation time;
# discover_plugins() merges these on top of the filesystem discovery so
# Account.typ and the create-account preset form pick them up uniformly.
_RUNTIME_PLUGINS = {}

# Lazy caches — filled on first access, invalidated only on explicit
# writes via ``set_disabled_plugins``.
_DISABLED_IDENTS_CACHE = None  # set[str] | None
_PLUGIN_DATA_CACHE = None  # dict[str, dict] | None — keyed by directory name


def _read_plugin_json(plugin_dir_path):
    """Read and return plugin.json data from a plugin directory, or None."""
    plugin_json_path = os.path.join(plugin_dir_path, 'plugin.json')
    if not os.path.exists(plugin_json_path):
        return None
    try:
        with open(plugin_json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def read_disabled_idents(path):
    """Return the set of disabled plugin idents stored at *path*, or empty
    on missing/corrupt file. Pure I/O — no caching, no globals."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
    except (json.JSONDecodeError, IOError):
        pass
    return set()


def write_disabled_idents(path, disabled):
    """Write the disabled-idents set to *path*, sorted."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sorted(disabled), f, indent=2)


def get_disabled_plugins():
    """Return the set of disabled plugin idents from ``disabled_plugins.json``."""
    return read_disabled_idents(_DISABLED_PLUGINS_PATH)


def set_disabled_plugins(disabled):
    """Write the set of disabled plugin idents to disk and clear the cache."""
    global _DISABLED_IDENTS_CACHE  # pylint: disable=global-statement
    write_disabled_idents(_DISABLED_PLUGINS_PATH, disabled)
    _DISABLED_IDENTS_CACHE = None


def _disabled_idents():
    """Cached set view of ``disabled_plugins.json``."""
    global _DISABLED_IDENTS_CACHE  # pylint: disable=global-statement
    if _DISABLED_IDENTS_CACHE is None:
        _DISABLED_IDENTS_CACHE = get_disabled_plugins()
    return _DISABLED_IDENTS_CACHE


def _plugin_data_cache():
    """Walk the bundled and repo-local plugin trees once and return a
    ``{directory_name: plugin_json_data}`` mapping."""
    global _PLUGIN_DATA_CACHE  # pylint: disable=global-statement
    if _PLUGIN_DATA_CACHE is not None:
        return _PLUGIN_DATA_CACHE
    cache = {}
    for sub in ('plugins', os.path.join('application', 'plugins')):
        plugin_root = os.path.join(_BASE_DIR, sub)
        if not os.path.isdir(plugin_root):
            continue
        for entry in os.listdir(plugin_root):
            entry_path = os.path.join(plugin_root, entry)
            if not os.path.isdir(entry_path):
                continue
            data = _read_plugin_json(entry_path)
            if data:
                cache[entry] = data
    _PLUGIN_DATA_CACHE = cache
    return _PLUGIN_DATA_CACHE


def is_plugin_disabled(dirname):
    """Return True iff *dirname* (or its plugin.json ident) is listed in
    ``disabled_plugins.json``. Plugins are enabled by default."""
    disabled = _disabled_idents()
    if dirname in disabled:
        return True
    data = _plugin_data_cache().get(dirname)
    return bool(data and data.get('ident') in disabled)


class _DisabledCliGroup:
    """Dummy CLI group that absorbs command/group registrations silently."""

    def __init__(self, name):
        self.name = name

    def command(self, *_args, **_kwargs):
        """Accept and discard command decorator."""
        def decorator(func):
            return func
        return decorator

    def group(self, *_args, **_kwargs):
        """Accept and discard sub-group decorator."""
        def decorator(func):
            return func
        return decorator


def register_cli_group(flask_app, name, plugin_dirname, help_text=""):
    """Register a CLI group for a plugin.

    Returns a real click group if the plugin is enabled,
    or a silent dummy group if it is disabled.
    """
    if is_plugin_disabled(plugin_dirname):
        return _DisabledCliGroup(name)

    @flask_app.cli.group(name=name, help=help_text)
    def cli_group():
        pass
    return cli_group


def register_plugin_type(ident, name, account_presets=None,
                         account_custom_field_presets=None,
                         description=''):
    """Register an Account plugin type from code (used by Enterprise).

    Idempotent: registering the same ident again overwrites the earlier
    entry, so Enterprise can call this on every process start without
    guarding against duplicates.
    """
    _RUNTIME_PLUGINS[ident] = {
        'ident': ident,
        'name': name,
        'description': description,
        'account_presets': dict(account_presets or {}),
        'account_custom_field_presets': dict(account_custom_field_presets or {}),
    }


def discover_plugins():
    """Discover account types from filesystem plugins + the runtime registry.

    Skips plugins that appear in ``disabled_plugins.json`` (matched by
    either directory name or ``ident``).
    """
    disabled = _disabled_idents()
    plugins = {}
    for entry, data in _plugin_data_cache().items():
        if entry in disabled:
            continue
        ident = data.get('ident')
        name = data.get('name')
        if not ident or not name or ident in disabled:
            continue
        plugins[ident] = data
    plugins.update(_RUNTIME_PLUGINS)
    return plugins
