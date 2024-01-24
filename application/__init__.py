""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
import os
import logging
from datetime import datetime
from pprint import pformat
from flask import Flask, url_for, redirect
from flask_admin import Admin
from flask_admin.menu import MenuLink
from flask_login import LoginManager
from flask_mail import Mail
from flask_bootstrap import Bootstrap
from flask_mongoengine import MongoEngine
from flask_admin.contrib.fileadmin import FileAdmin


VERSION = '3.5.3'
# create logger
logger = logging.getLogger('cmdb_syncer')

app = Flask(__name__)
env = os.environ.get('config')
if env == "prod":
    app.config.from_object('application.config.ProductionConfig')
elif env == "compose":
    app.config.from_object('application.config.ComposeConfig')
else:
    app.config.from_object('application.config.BaseConfig')
    app.jinja_env.auto_reload = True

try:
    from local_config import config
    app.config.update(config)
except ModuleNotFoundError:
    pass
logger.setLevel(logging.DEBUG)

ch = app.config['LOG_CHANNEL']
ch.setLevel(app.config['LOG_LEVEL'])

formatter = logging.Formatter('%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)
if app.config['DEBUG']:
    logger.info('Loaded Debug Mode')


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

# Wired new behavior in UWSGI:
# Master Process seams not to get the db init like before
# So we init it, try again if we are in a worker and fall back like before
db = MongoEngine(app)
try:
    db = MongoEngine()
    from uwsgidecorators import postfork

    @postfork
    def setup_db():
        """db init in uwsgi"""
        db.init_app(app)
except ImportError:
    db = MongoEngine(app)

# We need the db in the Module
from application.modules.log.log import Log


log = Log()

mail = Mail(app)
bootstrap = Bootstrap(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = False

cron_register = {}
from plugins import *
from application.plugins import *

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

from application.api.views import API_BP as api
app.register_blueprint(api, url_prefix="/api/v1")

admin = Admin(app, name=f"CMDB Syncer {VERSION}",
                   template_mode='bootstrap4', index_view=IndexView())


#   .-- Host
from application.models.host import Host
from application.views.host import HostModelView, ObjectModelView
admin.add_view(HostModelView(Host, name="Hosts"))
admin.add_view(ObjectModelView(Host, name="Objects", endpoint="Objects"))
#.
#   .-- Global
from application.modules.custom_attributes.models import CustomAttributeRule
from application.modules.custom_attributes.views import CustomAttributeView
admin.add_view(CustomAttributeView(CustomAttributeRule, name="Custom Attributes", category="Rules"))
#.
#   .-- Checkmk
admin.add_sub_category(name="Checkmk", parent_name="Rules")
admin.add_link(MenuLink(name='Debug Config', category='Checkmk',
                        url=f"{app.config['BASE_PREFIX']}admin/checkmkrule/debug"))

from application.modules.checkmk.models import CheckmkRule, CheckmkGroupRule, CheckmkFilterRule
from application.modules.checkmk.views import CheckmkRuleView, CheckmkGroupRuleView


from application.modules.checkmk.models import CheckmkRewriteAttributeRule
admin.add_view(RewriteAttributeView(CheckmkRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="Checkmk"))
admin.add_view(FiltereModelView(CheckmkFilterRule, name="Filter", category="Checkmk"))
admin.add_view(CheckmkRuleView(CheckmkRule, name="Export Rules", category="Checkmk"))
admin.add_view(CheckmkGroupRuleView(CheckmkGroupRule, \
                                    name="Checkmk Groups Management", category="Checkmk"))

from application.modules.checkmk.models import CheckmkInventorizeAttributes
admin.add_view(DefaultModelView(CheckmkInventorizeAttributes, name="Inventorize Settings",
                                                            category="Checkmk"))

from application.modules.checkmk.models import CheckmkRuleMngmt
from application.modules.checkmk.views import CheckmkMngmtRuleView
admin.add_view(CheckmkMngmtRuleView(CheckmkRuleMngmt, \
                                    name="Checkmk Rules Management", category="Checkmk"))

from application.modules.checkmk.models import CheckmkTagMngmt
from application.modules.checkmk.views import CheckmkTagMngmtView
admin.add_view(CheckmkTagMngmtView(CheckmkTagMngmt, name="Checkmk Tags", category="Checkmk"))

from application.modules.checkmk.models import CheckmkUserMngmt
from application.modules.checkmk.views import CheckmkUserMngmtView
admin.add_view(CheckmkUserMngmtView(CheckmkUserMngmt, name="Checkmk User", category="Checkmk"))


admin.add_sub_category(name="Checkmk Server", parent_name="Checkmk")
from application.modules.checkmk.models import CheckmkSettings, CheckmkSite
from application.modules.checkmk.views import CheckmkSettingsView, CheckmkSiteView
admin.add_view(CheckmkSettingsView(CheckmkSettings, name="Server Settings", \
                                                            category="Checkmk Server"))
admin.add_view(CheckmkSiteView(CheckmkSite, name="Site Settings", category="Checkmk Server"))

admin.add_sub_category(name="Business Intelligence", parent_name="Checkmk")
from application.modules.checkmk.models import CheckmkBiAggregation, CheckmkBiRule
from application.modules.checkmk.views import CheckmkBiRuleView
admin.add_view(CheckmkBiRuleView(CheckmkBiAggregation, name="BI Aggregation",\
                                                            category="Business Intelligence"))
admin.add_view(CheckmkBiRuleView(CheckmkBiRule, name="BI Rule", category="Business Intelligence"))

from application.modules.checkmk.models import CheckmkFolderPool
from application.modules.checkmk.views import CheckmkFolderPoolView
admin.add_view(CheckmkFolderPoolView(CheckmkFolderPool, name="Folder Pools", category="Checkmk"))

from application.modules.checkmk.models import CheckmkObjectCache
from application.modules.checkmk.views import CheckmkCacheView

admin.add_view(CheckmkCacheView(CheckmkObjectCache, \
                                    name="Object Cache", category="Checkmk"))


#.
#   .-- Ansible
admin.add_sub_category(name="Ansible", parent_name="Rules")
from application.modules.ansible.models import AnsibleCustomVariablesRule, \
                                        AnsibleFilterRule, AnsibleRewriteAttributesRule
from application.modules.ansible.views import AnsibleCustomVariablesView

admin.add_view(RewriteAttributeView(AnsibleRewriteAttributesRule, name="Rewrite Attributes",
                                                            category="Ansible"))
admin.add_view(FiltereModelView(AnsibleFilterRule, name="Filter", category="Ansible"))
admin.add_view(AnsibleCustomVariablesView(AnsibleCustomVariablesRule,\
                                    name="Custom Variables", category="Ansible"))
#.
#   .-- Netbox
admin.add_sub_category(name="Netbox", parent_name="Rules")

from application.modules.netbox.views import NetboxCustomAttributesView
from application.modules.netbox.models import NetboxCustomAttributes, \
                                                NetboxRewriteAttributeRule
admin.add_view(RewriteAttributeView(NetboxRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxCustomAttributes,\
                                    name="Custom Attributes", category="Netbox"))
#.
#   .-- Config
from application.models.account import Account
from application.views.account import AccountModelView
admin.add_view(AccountModelView(Account, name="Accounts", category="Config"))

from application.models.user import User
from application.views.user import UserView
admin.add_view(UserView(User, category='Config'))

from application.models.config import Config
from application.views.config import ConfigModelView

admin.add_view(ConfigModelView(Config, name="System Config", category="Config"))

if os.path.exists(app.config['FILEADMIN_PATH']):
    admin.add_view(FileAdmin(app.config['FILEADMIN_PATH'], name="Files", category="Config"))
#.
#   .-- Cron

admin.add_sub_category(name="Cronjobs", parent_name="Config")
from application.models.cron import CronGroup, CronStats
from application.views.cron import CronStatsView, CronGroupView
admin.add_view(CronGroupView(CronGroup, name="Cronjob Group", category="Cronjobs"))
admin.add_view(CronStatsView(CronStats, name="State Table", category="Cronjobs"))

#.



#   .-- Rest
admin.add_link(MenuLink(name='Change Password', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}change-password"))
admin.add_link(MenuLink(name='Set 2FA Code', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}set-2fa"))
admin.add_link(MenuLink(name='Logout', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}logout"))

from application.modules.log.models import LogEntry
from application.modules.log.views import LogView
admin.add_view(LogView(LogEntry, name="Log"))
#.
admin.add_link(MenuLink(name='Commit Changes',
                        url="#activate_changes",
                        class_name="toggle_activate_modal"))
