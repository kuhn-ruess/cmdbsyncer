""" Main entry """
# pyright: reportImportCycles=false
import os
import sys
import logging
import importlib
import pkgutil
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

from application.helpers.tablib_formater import ExportObjects

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

tablib_registry.register('syncer_rules', ExportObjects())


def _read_version_from_changelog():
    """
    Resolve the current version from the newest changelog/v*.md file by
    reading its first `## Version x.y.z` header. This keeps VERSION in sync
    with the changelog without requiring a manual bump on every release.
    """
    import glob
    import re as _re
    changelog_dir = os.path.join(os.path.dirname(__file__), "..", "changelog")
    files = glob.glob(os.path.join(changelog_dir, "v*.md"))

    def _key(path):
        m = _re.search(r"v(\d+)\.(\d+)\.md$", path)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    for path in sorted(files, key=_key, reverse=True):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = _re.match(r"^## Version (\d+\.\d+\.\d+)\s*$", line)
                if m:
                    return m.group(1)
    return "0.0.0"


VERSION = _read_version_from_changelog()

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
csrf = CSRFProtect(app)


## Read Build Data

for line in open(f"{app.root_path}/../buildinfo.txt").readlines():
    name, key = line.split('=')
    app.config[name] = key.strip()

log_config.dictConfig(app.config['LOGGING'])
logger = logging.getLogger('debug')


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

try:
    db = MongoEngine()
    from uwsgidecorators import postfork

    @postfork
    def setup_db():
        """db init in uwsgi"""
        db.init_app(app)

except ImportError:
    #print("   \033[91mWARNING: STANDALONE MODE - NOT FOR PROD\033[0m")
    #print(" * HINT: uwsgi modul not loaded")
    # Output makes problems for commands
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


from application.views.default import IndexView, DefaultModelView

from application.auth.views import AUTH
app.register_blueprint(AUTH)

from application.modules.rule.views import FiltereModelView, RewriteAttributeView

@app.route('/')
def page_redirect():
    """
    Redirect to admin Panel
    """
    return redirect(url_for("admin.index"))

def _register_all_plugin_admin_views():
    import application.plugins as plugins_package
    import plugins as external_plugins_package

    modules = []

    for _, module_name, _ in pkgutil.iter_modules(
        external_plugins_package.__path__, external_plugins_package.__name__ + "."
    ):
        modules.append(module_name)

    for _, module_name, _ in pkgutil.iter_modules(
        plugins_package.__path__, plugins_package.__name__ + "."
    ):
        modules.append(module_name)

    for module_name in modules:
        admin_module_name = f"{module_name}.admin_views"
        try:
            admin_module = importlib.import_module(admin_module_name)
        except ModuleNotFoundError as exc:
            if exc.name == admin_module_name:
                continue
            raise
        except Exception:
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

admin = Admin(app, name=f"cmdbsyncer {VERSION}",
                   index_view=IndexView(),
                   category_icon_classes={
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
                       'Profile': 'fa fa-user-cog',
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
    csrf.exempt(file_admin_view.blueprint)

from application.modules.log.models import LogEntry
from application.modules.log.views import LogView
admin.add_view(LogView(LogEntry, name="Log", menu_icon_type='fa', menu_icon_value='fa-file-text-o'))

#.
#   .-- Config
admin.add_category(name="Profile", icon_type='fa', icon_value='fa-user-cog')
from application.models.user import User
from application.views.user import UserView
admin.add_view(UserView(User, category='Profile', menu_icon_type='fa', menu_icon_value='fa-user'))

from application.models.config import Config
from application.views.config import ConfigModelView

admin.add_view(ConfigModelView(Config, name="System Config", category="Profile", menu_icon_type='fa', menu_icon_value='fa-cogs'))
#.

#   .-- Rest
admin.add_link(MenuLink(name='Change Password', category='Profile',
                        url=f"{app.config['BASE_PREFIX']}change-password",
                        icon_type='fa', icon_value='fa-key'))
admin.add_link(MenuLink(name='Set 2FA Code', category='Profile',
                        url=f"{app.config['BASE_PREFIX']}set-2fa",
                        icon_type='fa', icon_value='fa-shield'))
admin.add_link(MenuLink(name='Logout', category='Profile',
                        url=f"{app.config['BASE_PREFIX']}logout",
                        icon_type='fa', icon_value='fa-sign-out'))

#.
admin.add_link(MenuLink(name='Commit Changes',
                        url="#activate_changes",
                        class_name="toggle_activate_modal btn btn-primary commit-changes-btn",
                        icon_type='fa', icon_value='fa-check-circle'))



from plugins import *
from application.plugins import *
