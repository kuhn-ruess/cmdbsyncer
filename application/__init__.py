""" Main entry """
# Flask app factory with intentional deferred imports to avoid circular imports.
# pylint: disable=wrong-import-position,import-outside-toplevel,ungrouped-imports,line-too-long,wildcard-import,unused-wildcard-import,cyclic-import
import os
import sys
import logging
import importlib
import pkgutil
import warnings
from logging import config as log_config
from tablib.formats import registry as tablib_registry
import mongoengine
from sortedcontainers import SortedDict
from flask import Flask, url_for, redirect
from flask_admin import Admin
from flask_admin.menu import MenuLink
from flask_login import LoginManager
from flask_mail import Mail
from flask_bootstrap import Bootstrap
from flask_mongoengine import MongoEngine
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from application.helpers.tablib_formater import ExportObjects

warnings.filterwarnings('ignore', category=UserWarning)

tablib_registry.register('syncer_rules', ExportObjects())


from application._version import __version__ as VERSION, get_display_version

DISPLAY_VERSION = get_display_version()

CONFIG_MAP = {
    'prod': 'application.config.ProductionConfig',
    'compose': 'application.config.ComposeConfig',
    'base': 'application.config.BaseConfig',
}

app = Flask(__name__)
config_name = os.environ.get('config', 'base').lower()
app.config.from_object(CONFIG_MAP.get(config_name, CONFIG_MAP['base']))
if config_name == "base":
    app.jinja_env.auto_reload = True
_trusted_proxies = int(app.config.get('TRUSTED_PROXIES', 0))
if _trusted_proxies > 0:
    # Apache/nginx reverse-proxy in front of the app. ProxyFix rewrites
    # request.scheme / request.remote_addr / request.host from the
    # X-Forwarded-* headers so request.is_secure reflects the real client
    # connection. Only enable when the app sits behind a trusted proxy —
    # leave at 0 for mod_wsgi or direct deployments, otherwise a client
    # can spoof X-Forwarded-Proto and bypass the HTTPS API-auth gate.
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=_trusted_proxies,
        x_proto=_trusted_proxies,
        x_host=_trusted_proxies,
    )

csrf = CSRFProtect(app)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=app.config.get('RATELIMIT_STORAGE_URI', 'memory://'),
    headers_enabled=True,
)


## Read Build Data

# buildinfo.txt lives inside the package so it ships with the wheel; the
# pre-commit hook rewrites it on every commit so dev runs also see a fresh
# timestamp. Missing file (e.g. running from a raw checkout without the
# hook installed) is not fatal — we just expose an 'unknown' build date.
_buildinfo_path = os.path.join(app.root_path, "buildinfo.txt")
if os.path.isfile(_buildinfo_path):
    with open(_buildinfo_path, encoding="utf-8") as _buildinfo:
        for line in _buildinfo:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            name, key = stripped.split('=', 1)
            app.config[name.strip()] = key.strip()
else:
    app.config.setdefault("BUILD_DATE", "unknown")

log_config.dictConfig(app.config['LOGGING'])
logger = logging.getLogger('debug')

# Hook registry is always safe to import — the enterprise package itself
# is loaded later via enterprise.load_package(), after `db` exists, to
# avoid a circular import (enterprise models → application.models.* →
# `from application import db`).
from application import enterprise  # noqa: E402
from application.enterprise import run_hook as enterprise_hook  # noqa: E402


try:
    from local_config import config
    app.config.update(config)
except ModuleNotFoundError:
    pass


if '--debug' in sys.argv:
    logger.setLevel(logging.DEBUG)

if app.config['DEBUG']:
    logger.info('Loaded Debug Mode')

## Sentry
if app.config['SENTRY_ENABLED']:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    def filter_events(event, _hint):
        """
        Filter a list of Exception from sending to sentry
        """
        excp = event.get('exception', {})
        values = excp.get('values', [])
        if values:
            excp_type = values[0]['type']
            if excp_type in [
                    'timeout',
                ]:
                return None
        return event

    sentry_sdk.init(
        dsn=app.config['SENTRY_DSN'],
        before_send=filter_events,
        integrations=[FlaskIntegration(),
                     ],
        release=VERSION
    )

db = MongoEngine(app)

def init_db():
    """DB Init for Multiprocessing Pool"""
    mongoengine.disconnect()
    with app.app_context():
        MongoEngine(app)


from application.helpers.sates import get_changes


@app.before_request
def load_before_request():
    """
    Helper to have up to date data for each request
    """
    app.config['CHANGES'] = get_changes()

# We need the db in the Module
from application.modules.log.log import Log


log = Log()

mail = Mail(app)
bootstrap = Bootstrap(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = False



cron_register = SortedDict()
plugin_register = []

# All module-level names the enterprise package might transitively reach
# into (db, cron_register, plugin_register, …) exist at this point, so it
# is finally safe to import the package. configure_logging still runs
# before the bulk of the factory so an enterprise build can swap in a
# structured / JSON log pipeline before blueprint/admin registration.
enterprise.load_package()
enterprise_hook('configure_logging', app, logger)


from application.views.default import IndexView, DefaultModelView

from application.auth.views import AUTH
app.register_blueprint(AUTH)

# Give the enterprise package a chance to register its own auth-related
# blueprints (e.g. the native OIDC client). No-op without the feature.
enterprise_hook('register_blueprints', app)

from application.modules.rule.views import FiltereModelView, RewriteAttributeView

@app.route('/')
def page_redirect():
    """
    Redirect to admin Panel
    """
    return redirect(url_for("admin.index"))

def _register_all_plugin_admin_views():
    from application.helpers.plugins import is_plugin_disabled
    import application.plugins as plugins_package
    try:
        import plugins as external_plugins_package
    except ModuleNotFoundError:
        # No custom plugins directory in the working directory — typical
        # for a fresh PyPI install before self_configure has run.
        external_plugins_package = None

    plugin_modules = []

    if external_plugins_package is not None:
        for _, module_name, _ in pkgutil.iter_modules(
            external_plugins_package.__path__, external_plugins_package.__name__ + "."
        ):
            # module_name is e.g. "plugins.netbox" — extract the short ident
            short_name = module_name.rsplit(".", 1)[-1]
            if is_plugin_disabled(short_name):
                logger.info("Plugin '%s' is disabled, skipping", short_name)
                continue
            plugin_modules.append(module_name)

    for _, module_name, _ in pkgutil.iter_modules(
        plugins_package.__path__, plugins_package.__name__ + "."
    ):
        short_name = module_name.rsplit(".", 1)[-1]
        if is_plugin_disabled(short_name):
            logger.info("Plugin '%s' is disabled, skipping", short_name)
            continue
        plugin_modules.append(module_name)

    for module_name in plugin_modules:
        admin_module_name = f"{module_name}.admin_views"
        try:
            admin_module = importlib.import_module(admin_module_name)
        except ModuleNotFoundError as exc:
            if exc.name == admin_module_name:
                continue
            raise
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to register admin views for plugin %s", module_name
            )
            if '--debug' in sys.argv:
                raise
            continue

        register = getattr(admin_module, "register_admin_views", None)
        if callable(register):
            register(admin)


from application.api.views import API_BP as api
app.register_blueprint(api, url_prefix="/api/v1")
csrf.exempt(api)

admin = Admin(app, name=f"cmdbsyncer {DISPLAY_VERSION}",
                   index_view=IndexView(),
                   category_icon_classes={
                       'Account': 'fa fa-user-circle',
                       'Accounts': 'fa fa-users',
                       'Ansible': 'fa fa-cogs',
                       'Checkmk': 'fa fa-heartbeat',
                       'Checkmk Server': 'fa fa-building',
                       'Cronjobs': 'fa fa-clock-o',
                       'i-doit': 'fa fa-sitemap',
                       'Manage Business Intelligence': 'fa fa-sitemap',
                       'Modules': 'fa fa-puzzle-piece',
                       'Netbox': 'fa fa-database',
                       'Plugin: Dataflow': 'fa fa-arrows',
                       'Settings': 'fa fa-cog',
                       'Syncer Rules': 'fa fa-bolt',
                       'VMware': 'fa fa-server'
                       })


#   .-- Host
from application.models.host import Host
from application.views.host import HostModelView, ObjectModelView, TemplateModelView
admin.add_view(HostModelView(Host, name="Hosts", menu_icon_type='fa', menu_icon_value='fa-server'))
admin.add_category(name="Objects", icon_type='fa', icon_value='fa-folder-open')
admin.add_view(ObjectModelView(Host, name="All Objects", endpoint="Objects",category="Objects", menu_icon_type='fa', menu_icon_value='fa-cubes'))
admin.add_view(TemplateModelView(Host, name="Templates", endpoint="Objects Templates",category="Objects", menu_icon_type='fa', menu_icon_value='fa-files-o'))
#.
#   .-- Global
from application.modules.custom_attributes.models import CustomAttributeRule
from application.modules.custom_attributes.views import CustomAttributeView
admin.add_view(CustomAttributeView(CustomAttributeRule, name="Global Custom Attributes", category="Modules", menu_icon_type='fa', menu_icon_value='fa-cog'))
#.

_register_all_plugin_admin_views()


from application.models.account import Account
from application.views.account import AccountModelView, ChildAccountModelView
admin.add_category(name="Accounts", icon_type='fa', icon_value='fa-users')
admin.add_view(AccountModelView(Account, name="Accounts", category="Accounts", menu_icon_type='fa', menu_icon_value='fa-user-circle'))
admin.add_view(ChildAccountModelView(Account, name="Config Childs", endpoint='account_childs', category="Accounts", menu_icon_type='fa', menu_icon_value='fa-users'))

from application.models.cron import CronGroup, CronStats
from application.views.cron import CronStatsView, CronGroupView
admin.add_view(CronGroupView(CronGroup, name="Cronjob Group", category="Cronjobs", menu_icon_type='fa', menu_icon_value='fa-calendar'))
admin.add_view(CronStatsView(CronStats, name="State Table", category="Cronjobs", menu_icon_type='fa', menu_icon_value='fa-table'))

from application.views.fileadmin import FileAdminView
if os.path.exists(app.config['FILEADMIN_PATH']):
    file_admin_view = FileAdminView(app.config['FILEADMIN_PATH'], name="Filemanager", menu_icon_type='fa', menu_icon_value='fa-folder-open')
    admin.add_view(file_admin_view)

#.
#   .-- Settings (admin-facing tools, distinct from per-user actions)
admin.add_category(name="Settings", icon_type='fa', icon_value='fa-cog')
# Pre-declare enterprise sub-categories so their views land in the
# right place when register_admin_views runs. Flask-Admin creates
# them lazily on first reference otherwise, but referenced as sub-
# categories here gives the menu structure a predictable order.
admin.add_sub_category(name="Security", parent_name="Settings")
admin.add_sub_category(name="Compliance", parent_name="Settings")
admin.add_sub_category(name="Notifications", parent_name="Settings")
admin.add_sub_category(name="Backups", parent_name="Settings")

from application.modules.log.models import LogEntry
from application.modules.log.views import LogView
admin.add_view(LogView(LogEntry, name="Log", category="Settings",
                       menu_icon_type='fa', menu_icon_value='fa-file-text-o'))

from application.models.user import User
from application.views.user import UserView
admin.add_view(UserView(User, category='Settings',
                        menu_icon_type='fa', menu_icon_value='fa-user'))

from application.models.config import Config
from application.views.config import ConfigModelView

admin.add_view(ConfigModelView(Config, name="System Config",
                               endpoint='config', category="Settings",
                               menu_icon_type='fa', menu_icon_value='fa-cogs'))
admin.add_link(MenuLink(name='Edit local_config.py', category='Settings',
                        endpoint='config.local_config_editor',
                        icon_type='fa', icon_value='fa-file-code-o'))

from application.views.license import LicenseView
admin.add_view(LicenseView(name="License", endpoint="license", category="Settings",
                           menu_icon_type='fa', menu_icon_value='fa-id-card'))

from application.models.notification_channel import NotificationChannel
from application.views.notification_channel import NotificationChannelView
admin.add_view(NotificationChannelView(
    NotificationChannel, name="Channels",
    category="Notifications",
    menu_icon_type='fa', menu_icon_value='fa-paper-plane'))

# Give the enterprise package one chance to inject its own admin views
# (Secrets Manager, JSON logs UI, …). No-op when no valid license is
# installed, so community builds never expose enterprise menu entries.
enterprise_hook('register_admin_views', admin)
#.

# Per-user actions as their own Flask-Admin category. Using the native
# category + MenuLink mechanism means Flask-Admin's own dropdown JS
# and CSS applies — no custom widget, no click-handling quirks.
admin.add_category(name='Account', icon_type='fa', icon_value='fa-user-circle')
admin.add_link(MenuLink(name='Change Password', category='Account',
                        url=f"{app.config['BASE_PREFIX']}change-password",
                        icon_type='fa', icon_value='fa-key'))
admin.add_link(MenuLink(name='Set 2FA Code', category='Account',
                        url=f"{app.config['BASE_PREFIX']}set-2fa",
                        icon_type='fa', icon_value='fa-shield'))
admin.add_link(MenuLink(name='Logout', category='Account',
                        url=f"{app.config['BASE_PREFIX']}logout",
                        icon_type='fa', icon_value='fa-sign-out'))

#.
admin.add_link(MenuLink(name='Commit Changes',
                        url="#activate_changes",
                        class_name="toggle_activate_modal btn btn-primary commit-changes-btn",
                        icon_type='fa', icon_value='fa-check-circle'))



try:
    from plugins import *
except ModuleNotFoundError:
    # Optional: no custom plugins package in the working directory.
    pass
from application.plugins import *
