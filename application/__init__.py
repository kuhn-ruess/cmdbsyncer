""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
# pylint: disable=line-too-long
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

from application.helpers.tablib_formater import ExportObjects


tablib_registry.register('syncer_rules', ExportObjects())

VERSION = '3.11.0-dev4'


app = Flask(__name__)
env = os.environ.get('config')
if env == "prod":
    app.config.from_object('application.config.ProductionConfig')
elif env == "compose":
    app.config.from_object('application.config.ComposeConfig')
else:
    app.config.from_object('application.config.BaseConfig')
    app.jinja_env.auto_reload = True


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
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to register admin views for plugin %s", module_name
            )
            continue

        register = getattr(admin_module, "register_admin_views", None)
        if callable(register):
            register(admin)


from application.api.views import API_BP as api
app.register_blueprint(api, url_prefix="/api/v1")

admin = Admin(app, name=f"CMDBsyncer {VERSION} {app.config['HEADER_HINT']}",
                   index_view=IndexView(),
                   category_icon_classes={
                       })


#   .-- Host
from application.models.host import Host
from application.views.host import HostModelView, ObjectModelView
admin.add_view(HostModelView(Host, name="Hosts"))
admin.add_view(ObjectModelView(Host, name="Objects", endpoint="Objects"))
#.
#   .-- Global
from application.modules.custom_attributes.models import CustomAttributeRule
from application.modules.custom_attributes.views import CustomAttributeView
admin.add_view(CustomAttributeView(CustomAttributeRule, name="Global Custom Attributes", category="Modules"))
#.

_register_all_plugin_admin_views()


from application.models.account import Account
from application.views.account import AccountModelView, ChildAccountModelView
admin.add_category(name="Accounts")
admin.add_view(AccountModelView(Account, name="Accounts", category="Accounts"))
admin.add_view(ChildAccountModelView(Account, name="Config Childs", endpoint='account_childs', category="Accounts"))

from application.models.cron import CronGroup, CronStats
from application.views.cron import CronStatsView, CronGroupView
admin.add_view(CronGroupView(CronGroup, name="Cronjob Group", category="Cronjobs"))
admin.add_view(CronStatsView(CronStats, name="State Table", category="Cronjobs"))

from application.views.fileadmin import FileAdminView
if os.path.exists(app.config['FILEADMIN_PATH']):
    admin.add_view(FileAdminView(app.config['FILEADMIN_PATH'], name="Filemanager"))

from application.modules.log.models import LogEntry
from application.modules.log.views import LogView
admin.add_view(LogView(LogEntry, name="Log"))

#.
#   .-- Config
from application.models.user import User
from application.views.user import UserView
admin.add_view(UserView(User, category='Syncer Config'))

from application.models.config import Config
from application.views.config import ConfigModelView

admin.add_view(ConfigModelView(Config, name="System Config", category="Syncer Config"))
#.

#   .-- Rest
admin.add_link(MenuLink(name='Change Password', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}change-password"))
admin.add_link(MenuLink(name='Set 2FA Code', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}set-2fa"))
admin.add_link(MenuLink(name='Logout', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}logout"))

#.
admin.add_link(MenuLink(name='Commit Changes',
                        url="#activate_changes",
                        class_name="toggle_activate_modal btn btn-primary"))





from plugins import *
from application.plugins import *

