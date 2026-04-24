"""Plugin discovery and enable/disable helpers."""
import os
import json

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DISABLED_PLUGINS_PATH = os.path.join(_BASE_DIR, 'disabled_plugins.json')

# Cache: computed once at first call, maps dirname -> bool (True = disabled)
_disabled_cache = None  # pylint: disable=invalid-name

# In-memory registry for plugin types that ship inside a pip-installed
# Enterprise package rather than as a directory under plugins/. Callers
# use register_plugin_type(...) at feature activation time; discover_plugins()
# merges these on top of the filesystem discovery so Account.typ and the
# create-account preset form pick them up uniformly.
_RUNTIME_PLUGINS = {}


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


def get_disabled_plugins():
    """Return the set of disabled plugin idents from disabled_plugins.json."""
    if not os.path.exists(_DISABLED_PLUGINS_PATH):
        return set()
    try:
        with open(_DISABLED_PLUGINS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
    except (json.JSONDecodeError, IOError):
        pass
    return set()


def set_disabled_plugins(disabled):
    """Write the set of disabled plugin idents to disk and clear cache."""
    global _disabled_cache  # pylint: disable=global-statement
    with open(_DISABLED_PLUGINS_PATH, 'w', encoding='utf-8') as f:
        json.dump(sorted(disabled), f, indent=2)
    _disabled_cache = None


def _build_disabled_cache():
    """Scan all plugin dirs once and build a dirname -> disabled mapping."""
    disabled_idents = get_disabled_plugins()
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
            if not data:
                continue
            ident = data.get('ident', entry)
            if entry in disabled_idents or ident in disabled_idents:
                cache[entry] = True
            elif not data.get('enabled', False):
                cache[entry] = True
            else:
                cache[entry] = False
    return cache


def is_plugin_disabled(dirname):
    """Check whether a plugin is disabled (cached after first call)."""
    global _disabled_cache  # pylint: disable=global-statement
    if _disabled_cache is None:
        _disabled_cache = _build_disabled_cache()
    return _disabled_cache.get(dirname, False)


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
        'enabled': True,
        'account_presets': dict(account_presets or {}),
        'account_custom_field_presets': dict(account_custom_field_presets or {}),
    }


def discover_plugins():
    """
    Discover account types from plugin.json files in plugin directories
    and from the runtime registry. Skips plugins that are disabled
    (via disabled_plugins.json or enabled flag).
    """
    plugins = {}
    for sub in ('plugins', os.path.join('application', 'plugins')):
        plugin_root = os.path.join(_BASE_DIR, sub)
        if not os.path.isdir(plugin_root):
            continue
        for entry in os.listdir(plugin_root):
            entry_path = os.path.join(plugin_root, entry)
            if not os.path.isdir(entry_path):
                continue
            if is_plugin_disabled(entry):
                continue
            data = _read_plugin_json(entry_path)
            if data and 'ident' in data and 'name' in data:
                plugins[data['ident']] = data
    # Runtime-registered plugins win over filesystem ones with the same
    # ident (Enterprise can refresh its presets without an FS write).
    plugins.update(_RUNTIME_PLUGINS)
    return plugins
