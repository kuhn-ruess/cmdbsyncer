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
from unittest.mock import MagicMock, patch

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
_application.init_db = MagicMock(name="stub.init_db")

# Subpackages that the real modules import from. We mark __path__ so that any
# later "from application.X import Y" resolves against sys.modules first.
_stub_package("application.modules", path=[])
_stub_package("application.modules.rule", path=[])
_stub_package("application.models", path=[])
_stub_package("application.plugins", path=[])
_stub_package("application.plugins.checkmk", path=[])
sys.modules["application.plugins.checkmk"].get_rule_preview = MagicMock(
    name="stub.get_rule_preview")
# Stubs for the plugin modules the host view imports debug entry points
# from. Minimal: expose a callable under the same name so `from … import
# get_X_debug_data` resolves — tests don't exercise the debug path.
_stub_package("application.plugins.netbox", path=[])
sys.modules["application.plugins.netbox"].get_device_debug_data = MagicMock(
    name="stub.get_device_debug_data")
_stub_package("application.plugins.ansible", path=[])
sys.modules["application.plugins.ansible"].get_ansible_debug_data = MagicMock(
    name="stub.get_ansible_debug_data")
_stub_package("application.plugins.idoit", path=[])
sys.modules["application.plugins.idoit"].get_idoit_debug_data = MagicMock(
    name="stub.get_idoit_debug_data")
_stub_package("application.plugins.vmware", path=[])
sys.modules["application.plugins.vmware"].get_vmware_debug_data = MagicMock(
    name="stub.get_vmware_debug_data")
_stub_package("application.plugins.jira_cloud", path=[])
sys.modules["application.plugins.jira_cloud"].get_jira_cloud_debug_data = MagicMock(
    name="stub.get_jira_cloud_debug_data")
_stub_package("application.modules.custom_attributes", path=[])
_stub_package("application.helpers", path=[])

# application.views.host_filters imports the search parser at module load
# time; stub it so test_api's direct importlib loader of host.py doesn't
# choke on an unresolved sub-module.
_search_parser = _stub_package("application.modules.search_parser")


class _SearchSyntaxError(Exception):  # pylint: disable=missing-class-docstring
    pass


_search_parser.parse_search = MagicMock(name="stub.parse_search", return_value=None)
_search_parser.SearchSyntaxError = _SearchSyntaxError


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


class _CmdbField:  # pylint: disable=too-few-public-methods
    """Stub CmdbField embedded doc — tests don't exercise persistence."""

    def __init__(self, field_name=None, field_value=None):
        self.field_name = field_name
        self.field_value = field_value


_models_host.CmdbField = _CmdbField
# Tests don't exercise the lifecycle-state filter, so an empty option list
# is enough to satisfy `from application.models.host import LIFECYCLE_STATES`.
_models_host.LIFECYCLE_STATES = ()
# Reserved sentinels for syncer-native ("CMDB Mode") objects.
_models_host.CMDB_SOURCE_ACCOUNT_ID = 'cmdb'
_models_host.CMDB_SOURCE_ACCOUNT_NAME = 'cmdb'
_models_host.RELATION_TYPES = ()
_models_host.RELATION_INVERSE_LABEL = {}


class _HostInventoryTreePath:  # pylint: disable=too-few-public-methods
    """Stub for the embedded path/value pair on a HostInventoryTree."""

    def __init__(self, path=None, value=None):
        self.path = path
        self.value = value


class _HostInventoryTree:  # pylint: disable=too-few-public-methods
    """Stub HostInventoryTree side-doc; tests patch .objects."""
    objects = MagicMock()


_models_host_inv_tree = _stub_package("application.models.host_inventory_tree")
_models_host_inv_tree.HostInventoryTreePath = _HostInventoryTreePath
_models_host_inv_tree.HostInventoryTree = _HostInventoryTree


# --- application.models.host_label_event -------------------------------------

class _HostLabelChange:  # pylint: disable=too-few-public-methods
    """Stub label-change entry; carries the fields the diff produces."""

    def __init__(self, key=None, old_value=None, new_value=None, change=None):
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.change = change


class _HostLabelEvent:  # pylint: disable=too-few-public-methods
    """Stub HostLabelEvent model; tests patch .objects if needed."""
    objects = MagicMock()


_models_host_label_event = _stub_package("application.models.host_label_event")
_models_host_label_event.HostLabelChange = _HostLabelChange
_models_host_label_event.HostLabelEvent = _HostLabelEvent


# --- application.models.project ----------------------------------------------

_models_project = _stub_package("application.models.project")
_models_project.Project = MagicMock(name="stub.Project")

# --- application.models.saved_search ---------------------------------------

_models_saved_search = _stub_package("application.models.saved_search")


class _SavedSearch:  # pylint: disable=too-few-public-methods
    """Stub SavedSearch model — tests don't exercise persistence."""
    objects = MagicMock()


_models_saved_search.SavedSearch = _SavedSearch


# --- mongoengine / flask_admin.contrib.mongoengine --------------------------
# Stubs mongoengine so modules under test can do `from mongoengine.errors
# import ...` without a live MongoDB. flask_admin.contrib.mongoengine is also
# stubbed because importing the real package eagerly pulls in Document /
# QuerySet / connection helpers that do not work against our empty stub.

_mongoengine = _stub_package("mongoengine", path=[])
_mongoengine.Document = type("Document", (), {})
_mongoengine.ValidationError = type("ValidationError", (Exception,), {})
_mongoengine.Q = type("Q", (), {})
_mongoengine.get_db = MagicMock(name="stub.get_db")
_mongoengine.DENY = 3


class _StubQuerySet:  # pylint: disable=too-few-public-methods
    """Stub mongoengine QuerySet — a base HostQuerySet can subclass.

    `delete` exists so tests can patch it and assert that the override
    delegates; it is never reached unpatched.
    """

    def delete(self, *args, **kwargs):
        """Never called unpatched — see the class docstring."""
        raise NotImplementedError("stub QuerySet.delete must be patched")


_mongoengine.QuerySet = _StubQuerySet

_mongoengine_errors = _stub_package("mongoengine.errors")
_mongoengine_errors.DoesNotExist = type("DoesNotExist", (Exception,), {})
_mongoengine_errors.MultipleObjectsReturned = type(
    "MultipleObjectsReturned",
    (Exception,),
    {},
)
_mongoengine_errors.NotUniqueError = type("NotUniqueError", (Exception,), {})
_mongoengine_errors.ValidationError = type("ValidationError", (Exception,), {})

# Replace the real flask_admin.contrib.mongoengine integration with a minimal
# stub that only exposes BaseMongoEngineFilter / ModelView so admin views load.
_fa_me = _stub_package("flask_admin.contrib.mongoengine", path=[])
_fa_me_filters = _stub_package("flask_admin.contrib.mongoengine.filters")


class _BaseMongoEngineFilter:  # pylint: disable=too-few-public-methods
    """Stub replacement for flask_admin's mongoengine filter base."""

    def __init__(self, *_args, **_kwargs):
        pass


_fa_me_filters.BaseMongoEngineFilter = _BaseMongoEngineFilter
_fa_me_filters.BooleanEqualFilter = type(
    "BooleanEqualFilter", (_BaseMongoEngineFilter,), {},
)
_fa_me_filters.FilterLike = type("FilterLike", (_BaseMongoEngineFilter,), {})
_fa_me.BaseMongoEngineFilter = _BaseMongoEngineFilter
_fa_me.ModelView = type("ModelView", (), {})


# --- application.helpers.cron -----------------------------------------------

_cron = _stub_package("application.helpers.cron")
_cron.register_cronjob = MagicMock(name="stub.register_cronjob")


# --- application.helpers.audit ----------------------------------------------
# Thin enterprise-hook wrapper; tests only care that the call site compiles.

_audit = _stub_package("application.helpers.audit")
_audit.audit = MagicMock(name="stub.audit")


# --- application.helpers.label_history --------------------------------------
# Recording label changes is off unless local_config.py enables it; the
# stub keeps that default so no test writes history documents.

_label_history = _stub_package("application.helpers.label_history")
_label_history.label_history_enabled = MagicMock(
    name="stub.label_history_enabled", return_value=False)
_label_history.label_history_retention_seconds = MagicMock(
    name="stub.label_history_retention_seconds", return_value=90 * 86400)


# --- Extra stubs for application.api tests ----------------------------------
# application.api imports User, Account, and the `log` object from application
# at import time. We register minimal stand-ins so test_api can load the real
# api source files without pulling in Flask-Admin / MongoDB.

_application.log = MagicMock(name="stub.log_object")

_models_user = _stub_package("application.models.user")


class _User:  # pylint: disable=too-few-public-methods
    """Stub User model; tests patch .objects per-test."""
    objects = MagicMock()


_models_user.User = _User
# application.api imports these at module load; auth tests patch the finder.
_models_user.find_user_by_api_token = MagicMock(
    name="stub.find_user_by_api_token", return_value=(None, None))
_models_user.API_TOKEN_PREFIX = 'cmdb_pat_'
# Mirrors the real helper so the API's read-only gate behaves in tests.
_models_user.is_readonly = lambda user: bool(getattr(user, 'readonly', False))

_models_account = _stub_package("application.models.account")


class _Account:  # pylint: disable=too-few-public-methods
    """Stub Account model."""
    objects = MagicMock()


class _CustomEntry:  # pylint: disable=too-few-public-methods
    """Stub Account.custom_fields embedded document."""
    name = None
    value = None


_models_account.Account = _Account
_models_account.CustomEntry = _CustomEntry
_models_account.object_types = []
# plugin.py folds the hosts a master account kept into its log entry.
_models_account.pop_master_skips = MagicMock(name="stub.pop_master_skips",
                                             return_value='')

_models_cron = _stub_package("application.models.cron")


class _CronStats:  # pylint: disable=too-few-public-methods
    """Stub CronStats model."""
    objects = MagicMock()


class _CronGroup:  # pylint: disable=too-few-public-methods
    """Stub CronGroup model."""
    objects = MagicMock()


_models_cron.CronStats = _CronStats
_models_cron.CronGroup = _CronGroup

_log_models = _stub_package("application.modules.log.models")


class _LogEntry:  # pylint: disable=too-few-public-methods
    """Stub LogEntry model."""
    objects = MagicMock()


_log_models.LogEntry = _LogEntry


# get_account helper
_get_account_mod = sys.modules.get("application.helpers.get_account")
if _get_account_mod is None:
    _get_account_mod = _stub_package("application.helpers.get_account")
_get_account_mod.get_account_by_name = MagicMock(name="stub.get_account_by_name")


class _AccountNotFoundError(Exception):
    """Stub exception matching the real one."""


_get_account_mod.AccountNotFoundError = _AccountNotFoundError
_get_account_mod.account_allows = MagicMock(
    name="stub.account_allows", return_value=True)


# --- application.helpers.plugins --------------------------------------------

_plugins_helper = _stub_package("application.helpers.plugins")
_plugins_helper.is_plugin_disabled = MagicMock(
    name="stub.is_plugin_disabled", return_value=False
)
_plugins_helper.register_cli_group = MagicMock(name="stub.register_cli_group")
_plugins_helper.read_disabled_idents = MagicMock(
    name="stub.read_disabled_idents", return_value=set()
)
_plugins_helper.write_disabled_idents = MagicMock(name="stub.write_disabled_idents")


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


def _try_load_real_module(module_name, relative_path):
    """Best-effort loader for tests that don't need every heavy dependency."""
    try:
        return _load_real_module(module_name, relative_path)
    except ModuleNotFoundError:
        sys.modules.pop(module_name, None)
        return None


_load_real_module(
    "application.modules.rule.match",
    os.path.join("modules", "rule", "match.py"),
)

# Pure standard-library helper — loaded for real so the rule analysis
# hashes attribute values exactly as production does.
_load_real_module(
    "application.helpers.label_hash",
    os.path.join("helpers", "label_hash.py"),
)

# Loaded for real: it only reads app.config, and the label-history tests
# exercise its retention clamping through it.
_load_real_module(
    "application.helpers.retention",
    os.path.join("helpers", "retention.py"),
)

# Loaded for real too: at import time it needs nothing but datetime and the
# stubbed mongoengine, and the host views import `relation_target` from it.
_load_real_module(
    "application.models.host_cleanup",
    os.path.join("models", "host_cleanup.py"),
)

# Same deal: template matching imports Host lazily inside its functions,
# so the module itself loads without the database.
_load_real_module(
    "application.models.host_templates",
    os.path.join("models", "host_templates.py"),
)

# application.modules.plugin pulls in render_jinja at import time, so the
# helpers.syncer_jinja stub must be in place before the real plugin module
# is loaded (the duplicated stub further down stays for the checkmk loaders
# that rely on it).
_syncer_jinja_early = _stub_package("application.helpers.syncer_jinja")
_syncer_jinja_early.render_jinja = MagicMock(name="stub.render_jinja")
_syncer_jinja_early.get_list = MagicMock(name="stub.get_list")

_try_load_real_module(
    "application.modules.plugin",
    os.path.join("modules", "plugin.py"),
)
_try_load_real_module(
    "application.plugins.checkmk.cmk2",
    os.path.join("plugins", "checkmk", "cmk2.py"),
)
# cmk_rules provides folder_in_scope, imported by syncer at module load, so it
# must be registered before the syncer module is loaded below.
_try_load_real_module(
    "application.plugins.checkmk.cmk_rules",
    os.path.join("plugins", "checkmk", "cmk_rules.py"),
)
_try_load_real_module(
    "application.plugins.checkmk.syncer",
    os.path.join("plugins", "checkmk", "syncer.py"),
)
# rule_passwords has no heavy imports (models are imported lazily), so it can be
# loaded directly for its own unit tests.
_try_load_real_module(
    "application.plugins.checkmk.rule_passwords",
    os.path.join("plugins", "checkmk", "rule_passwords.py"),
)
# data_quality only imports csv/io/json at module level (CMK2 is lazy), so it
# loads cleanly for its own CSV-parsing / report-join unit tests.
_try_load_real_module(
    "application.plugins.checkmk.data_quality",
    os.path.join("plugins", "checkmk", "data_quality.py"),
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
_get_account.AccountNotFoundError = _AccountNotFoundError
_get_account.account_allows = MagicMock(
    name="stub.account_allows", return_value=True)
# Context manager used by the admin views; tests that exercise the real
# masking load the real module themselves (see test_security_fixes).
_get_account.mask_account_secrets = MagicMock(name="stub.mask_account_secrets")

# application.plugins.checkmk.models
_cmk_models = _stub_package("application.plugins.checkmk.models")
for _name in (
    "CheckmkFolderPool", "CheckmkObjectCache", "CheckmkGroupRule",
    "CheckmkTagMngmt", "CheckmkUserMngmt", "CheckmkPassword",
    "CheckmkInventorizeAttributes", "CheckmkRuleMngmt",
    "RuleMngmtOutcome",
    "CheckmkBiRule", "CheckmkBiAggregation", "CheckmkDowntimeRule",
    "CheckmkRewriteAttributeRule", "CheckmkFilterRule", "CheckmkDCDRule",
    "CheckmkNotificationRule",
    "CheckmkSite", "CheckmkSettings",
    "CheckmkSitePool", "CheckmkSitePoolMember",
):
    setattr(_cmk_models, _name, MagicMock(name=f"stub.{_name}"))

# Real value so rules.py can map built-in convenience actions to attributes.
_cmk_models.BUILTIN_ATTRIBUTE_ACTIONS = {
    "set_ip_address_family": "tag_address_family",
    "set_ipaddress": "ipaddress",
    "set_ipv6address": "ipv6address",
    "set_agent": "tag_agent",
    "set_snmp": "tag_snmp_ds",
    "set_piggyback": "tag_piggyback",
    "set_criticality": "tag_criticality",
    "set_networking": "tag_networking",
    "set_alias": "alias",
    "set_site": "site",
}

# application.models.host extras
_models_host.app = _StubApp()
_models_host.HostError = type("HostError", (Exception,), {})


def _stub_get_cmdb_model_fields(object_type="host"):
    """Mirror of application.models.host.get_cmdb_model_fields."""
    cmdb_models = _models_host.app.config.get("CMDB_MODELS", {}) or {}
    fields = dict(cmdb_models.get(object_type, {}) or {})
    fields.update(cmdb_models.get("all", {}) or {})
    return fields


_models_host.get_cmdb_model_fields = _stub_get_cmdb_model_fields

# application.init_db
_application.init_db = MagicMock(name="stub.init_db")

# Load real plugin modules
_try_load_real_module(
    "application.modules.rule.rule",
    os.path.join("modules", "rule", "rule.py"),
)
# checkmk/inits.py imports Filter and Rewrite at module import time.
_try_load_real_module(
    "application.modules.rule.filter",
    os.path.join("modules", "rule", "filter.py"),
)
_try_load_real_module(
    "application.modules.rule.rewrite",
    os.path.join("modules", "rule", "rewrite.py"),
)
for _mod_name, _mod_path in [
    ("helpers", "helpers.py"),
    ("poolfolder", "poolfolder.py"),
    ("sitepool", "sitepool.py"),
    ("rules", "rules.py"),
    ("bi", "bi.py"),
    # cmk_rules is loaded earlier (before syncer) — see above.
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
    ("notification_rules", "notification_rules.py"),
    # inits imports the other checkmk submodules above, so it loads last.
    ("inits", "inits.py"),
]:
    _try_load_real_module(
        f"application.plugins.checkmk.{_mod_name}",
        os.path.join("plugins", "checkmk", _mod_path),
    )


# --- Netbox plugin modules ---------------------------------------------------
# devices.py does `from .netbox import SyncNetbox`, so the base module has to be
# loaded first. Loaded here (not in the plugin test __init__) for the same
# reason as checkmk: unittest discover does not reliably run package __init__.py.
# utils.py holds the shared parse_import_filter helper that devices.py imports,
# so it has to be registered before devices.
_try_load_real_module(
    "application.plugins.netbox.utils",
    os.path.join("plugins", "netbox", "utils.py"),
)
_try_load_real_module(
    "application.plugins.netbox.netbox",
    os.path.join("plugins", "netbox", "netbox.py"),
)
_try_load_real_module(
    "application.plugins.netbox.devices",
    os.path.join("plugins", "netbox", "devices.py"),
)


# --- Jira Cloud plugin modules -----------------------------------------------
# jira_cloud.py holds the base class both the import and the export use; it
# only needs the syncerapi + plugin stubs above.
_try_load_real_module(
    "application.plugins.jira_cloud.jira_cloud",
    os.path.join("plugins", "jira_cloud", "jira_cloud.py"),
)


# --- API modules under test -------------------------------------------------
# Load the real api/__init__, api/syncer, api/objects files under their
# canonical module names. They import User/Account/LogEntry/Host etc. from
# the stubs above — no live MongoDB needed.
_try_load_real_module(
    "application.helpers.mongo_keys",
    os.path.join("helpers", "mongo_keys.py"),
)
_stub_package("application.api", path=[os.path.join(_APP_ROOT, "api")])
_try_load_real_module(
    "application.api",
    os.path.join("api", "__init__.py"),
)
_try_load_real_module(
    "application.api.syncer",
    os.path.join("api", "syncer.py"),
)
_try_load_real_module(
    "application.api.objects",
    os.path.join("api", "objects.py"),
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


def make_checkmk_rule_sync():
    """
    Build a CheckmkRuleSync with CMK2.__init__ stubbed out. The patch only
    has to be active while __init__ runs — base_mock_init sets every
    attribute the tests need as plain instance state — so a context manager
    is enough and no per-test teardown is required. Shared by the checkmk
    rule test modules so the construction dance lives in one place.

    cmk_rules is pulled from sys.modules (the real module was loaded above by
    _load_real_module) rather than imported, because a top-level import here
    would run before the bootstrap installs the stubs it depends on.
    """
    cmk_rules = sys.modules['application.plugins.checkmk.cmk_rules']
    with patch('application.plugins.checkmk.cmk_rules.CMK2.__init__',
               lambda self_param, account=False, **_kwargs: base_mock_init(
                   self_param, rulsets_by_type={})):
        return cmk_rules.CheckmkRuleSync()
