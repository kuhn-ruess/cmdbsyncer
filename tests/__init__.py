"""
Test package bootstrap.

Running the existing test suite used to require a live MongoDB because
`import application` triggers Flask-Admin's `scaffold_form()`, which eagerly
queries the database. For unit tests we don't want that dependency.

This module installs stub entries in `sys.modules` for `application` and the
transitively imported helpers BEFORE any test module is loaded. The real
files under test (`application/modules/plugin.py`,
`application/plugins/checkmk/cmk2.py`, `application/plugins/checkmk/syncer.py`)
are then loaded directly via `importlib.util` and registered under their
canonical names, so the test files' normal `from application... import ...`
statements resolve from the sys.modules cache without ever touching MongoDB.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_ROOT = os.path.join(_REPO_ROOT, "application")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _stub_package(name, path=None):
    """Register an empty stub module in sys.modules."""
    mod = types.ModuleType(name)
    if path is not None:
        # Marking __path__ makes it a package, so child modules are allowed.
        mod.__path__ = path
    sys.modules[name] = mod
    return mod


class _StubApp:  # pylint: disable=too-few-public-methods
    """Minimal replacement for the Flask `app` object used at import time."""

    # `@app.cli.group(...)` is evaluated at import time in cmk2.py. A MagicMock
    # handles the decorator chain without us having to know the exact shape.
    cli = MagicMock(name="stub.app.cli")
    config = {
        # Plugin base class
        "HTTP_REQUEST_TIMEOUT": 30,
        "HTTP_MAX_RETRIES": 3,
        "HTTP_REPEAT_TIMEOUT": 5,
        "DISABLE_SSL_ERRORS": False,
        # Rule engine
        "ADVANCED_RULE_DEBUG": False,
        # Checkmk syncer
        "PROCESS_TIMEOUT": 30,
        "CMK_GET_HOST_BY_FOLDER": False,
        "CMK_DONT_DELETE_HOSTS": False,
        "CMK_DETAILED_LOG": True,
        "CMK_BULK_DELETE_HOSTS": True,
        "CMK_BULK_DELETE_OPERATIONS": 100,
        "CMK_BULK_CREATE_HOSTS": True,
        "CMK_BULK_CREATE_OPERATIONS": 50,
        "CMK_BULK_UPDATE_HOSTS": True,
        "CMK_BULK_UPDATE_OPERATIONS": 50,
        "CMK_COLLECT_BULK_OPERATIONS": False,
        "CMK_WRITE_STATUS_BACK": False,
        "CMK_LOWERCASE_LABEL_VALUES": False,
    }


# --- Top-level stubs ---------------------------------------------------------

_application = _stub_package("application", path=[_APP_ROOT])
_application.app = _StubApp()
_application.logger = MagicMock(name="stub.logger")
_application.log = MagicMock(name="stub.log")
_application.db = MagicMock(name="stub.db")

# Subpackages that the real modules import from. We mark __path__ so that any
# later "from application.X import Y" resolves against sys.modules first.
_stub_package("application.modules", path=[])
_stub_package("application.modules.rule", path=[])
_stub_package("application.models", path=[])
_stub_package("application.plugins", path=[])
_stub_package("application.plugins.checkmk", path=[])
_stub_package("application.modules.custom_attributes", path=[])
_stub_package("application.helpers", path=[])


# --- application.modules.custom_attributes.models ----------------------------

_cust_models = _stub_package("application.modules.custom_attributes.models")


class _CustomAttributeRuleModel:  # pylint: disable=too-few-public-methods
    """Stub model; tests replace .objects with a Mock via @patch."""
    objects = MagicMock()


_cust_models.CustomAttributeRule = _CustomAttributeRuleModel


# --- application.modules.custom_attributes.rules -----------------------------

_cust_rules = _stub_package("application.modules.custom_attributes.rules")


class _CustomAttributeRule:  # pylint: disable=too-few-public-methods
    """Stub rules handler; tests replace the whole class via @patch."""

    def __init__(self):
        self.debug = False
        self.rules = []


_cust_rules.CustomAttributeRule = _CustomAttributeRule


# --- application.modules.debug ----------------------------------------------

_debug = _stub_package("application.modules.debug")
_debug.attribute_table = MagicMock(name="stub.attribute_table")


class _ColorCodes:  # pylint: disable=too-few-public-methods
    """Mirror application.modules.debug.ColorCodes so tests can assert on
    the exact ANSI escape sequences that the syncer prints."""
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


_debug.ColorCodes = _ColorCodes
_debug.cc = _ColorCodes
_debug.debug = MagicMock(name="stub.debug")


# --- application.models.host ------------------------------------------------

_models_host = _stub_package("application.models.host")


class _Host:  # pylint: disable=too-few-public-methods
    """Stub Host model; tests patch objects / objects_by_filter as needed."""
    objects = MagicMock()
    objects_by_filter = MagicMock()


_models_host.Host = _Host


# --- application.helpers.cron -----------------------------------------------

_cron = _stub_package("application.helpers.cron")
_cron.register_cronjob = MagicMock(name="stub.register_cronjob")


# --- syncerapi.v1 -----------------------------------------------------------
# plugin.py imports get_account/Host/cc from here. The real module re-exports
# from application, which causes a circular import during stand-alone loads.
_stub_package("syncerapi", path=[])
_syncerapi_v1 = _stub_package("syncerapi.v1")
_syncerapi_v1.get_account = MagicMock(name="stub.get_account")
_syncerapi_v1.Host = _Host
_syncerapi_v1.cc = _ColorCodes
_syncerapi_v1.render_jinja = MagicMock(name="stub.render_jinja")


# --- Real modules under test -------------------------------------------------
# Load the actual source files directly and register them under their canonical
# module names, bypassing `application/__init__.py` entirely.

def _load_real_module(module_name, relative_path):
    """Execute a source file as a module and install it in sys.modules."""
    file_path = os.path.join(_APP_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec and spec.loader, f"Cannot load spec for {module_name}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_load_real_module(
    "application.modules.rule.match",
    os.path.join("modules", "rule", "match.py"),
)
_load_real_module(
    "application.modules.plugin",
    os.path.join("modules", "plugin.py"),
)
_load_real_module(
    "application.plugins.checkmk.cmk2",
    os.path.join("plugins", "checkmk", "cmk2.py"),
)
_load_real_module(
    "application.plugins.checkmk.syncer",
    os.path.join("plugins", "checkmk", "syncer.py"),
)


# --- Checkmk plugin modules --------------------------------------------------
# Additional stubs and module loads needed by checkmk plugin tests.
# These live here (not in the plugin test directory) because the test bootstrap
# must run before any import statement, and unittest discover does not reliably
# execute package __init__.py files.

# application.helpers.syncer_jinja
_syncer_jinja = _stub_package("application.helpers.syncer_jinja")
_syncer_jinja.render_jinja = MagicMock(name="stub.render_jinja")
_syncer_jinja.get_list = MagicMock(name="stub.get_list")

# application.helpers.get_account
_get_account = _stub_package("application.helpers.get_account")
_get_account.get_account_by_name = MagicMock(name="stub.get_account_by_name")

# application.plugins.checkmk.models
_cmk_models = _stub_package("application.plugins.checkmk.models")
for _name in (
    "CheckmkFolderPool", "CheckmkObjectCache", "CheckmkGroupRule",
    "CheckmkTagMngmt", "CheckmkUserMngmt", "CheckmkPassword",
    "CheckmkInventorizeAttributes", "CheckmkRuleMngmt",
    "CheckmkSite", "CheckmkSettings",
):
    setattr(_cmk_models, _name, MagicMock(name=f"stub.{_name}"))

# application.models.host extras
_models_host.app = _StubApp()
_models_host.HostError = type("HostError", (Exception,), {})

# application.init_db
_application.init_db = MagicMock(name="stub.init_db")

# Load real plugin modules
_load_real_module(
    "application.modules.rule.rule",
    os.path.join("modules", "rule", "rule.py"),
)
for _mod_name, _mod_path in [
    ("helpers", "helpers.py"),
    ("poolfolder", "poolfolder.py"),
    ("rules", "rules.py"),
    ("bi", "bi.py"),
    ("cmk_rules", "cmk_rules.py"),
    ("dcd", "dcd.py"),
    ("downtimes", "downtimes.py"),
    ("groups", "groups.py"),
    ("passwords", "passwords.py"),
    ("sites", "sites.py"),
    ("tags", "tags.py"),
    ("users", "users.py"),
    ("inventorize", "inventorize.py"),
    ("import_v1", "import_v1.py"),
    ("import_v2", "import_v2.py"),
]:
    _load_real_module(
        f"application.plugins.checkmk.{_mod_name}",
        os.path.join("plugins", "checkmk", _mod_path),
    )


# --- Shared test helper ------------------------------------------------------
# Avoids duplicate setUp code across checkmk test files (pylint R0801).

def base_mock_init(self_param, **overrides):
    """Common mock __init__ for CMK2 subclasses in tests."""
    defaults = {
        'account_id': 'test_account',
        'account_name': 'Test',
        'config': {'settings': {}},
        'log_details': [],
        'checkmk_version': '2.3.0',
        'actions': MagicMock(),
        'name': 'test',
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(self_param, key, value)
