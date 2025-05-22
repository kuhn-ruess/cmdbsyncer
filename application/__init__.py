""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
# pylint: disable=line-too-long
import os
import sys
import logging
from logging import config as log_config
from datetime import datetime
from sortedcontainers import SortedDict
from pprint import pformat
from jinja2 import StrictUndefined
from flask import Flask, url_for, redirect
from flask_admin import Admin
from flask_admin.menu import MenuLink
from flask_login import LoginManager
from flask_mail import Mail
from flask_bootstrap import Bootstrap
from flask_mongoengine import MongoEngine
from flask_admin.contrib.fileadmin import FileAdmin


from application.helpers.tablib_formater import ExportObjects
from tablib.formats import registry as tablib_registry

import mongoengine

tablib_registry.register('syncer_rules', ExportObjects())


VERSION = '3.9.0-beta1'

# create logger


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

admin = Admin(app, name=f"CMDBsyncer {VERSION} {app.config['HEADER_HINT']}",
                   template_mode='bootstrap4', index_view=IndexView(),
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
#   .-- Ansible
admin.add_sub_category(name="Ansible", parent_name="Modules")
from application.modules.ansible.models import AnsibleCustomVariablesRule, \
                                        AnsibleFilterRule, AnsibleRewriteAttributesRule
from application.modules.ansible.views import AnsibleCustomVariablesView

admin.add_view(RewriteAttributeView(AnsibleRewriteAttributesRule, name="Rewrite Attributes",
                                                            category="Ansible"))
admin.add_view(FiltereModelView(AnsibleFilterRule, name="Filter", category="Ansible"))
admin.add_view(AnsibleCustomVariablesView(AnsibleCustomVariablesRule,\
                                    name="Ansible Attributes", category="Ansible"))
#.
#   .-- Checkmk
admin.add_sub_category(name="Checkmk", parent_name="Modules")
admin.add_link(MenuLink(name='Debug Config', category='Checkmk',
                        url=f"{app.config['BASE_PREFIX']}admin/checkmkrule/debug"))

from application.modules.checkmk.models import CheckmkRule, CheckmkGroupRule, CheckmkFilterRule
from application.modules.checkmk.views import CheckmkRuleView, CheckmkGroupRuleView


from application.modules.checkmk.models import CheckmkRewriteAttributeRule
admin.add_view(RewriteAttributeView(CheckmkRewriteAttributeRule, name="Rewrite and Create Custom Syncer Attributes",
                                                            category="Checkmk"))
admin.add_view(FiltereModelView(CheckmkFilterRule, name="Filter Hosts and Whiteliste Checkmk Labels", category="Checkmk"))
admin.add_view(CheckmkRuleView(CheckmkRule, name="Set Folder and  Attributes of Host", category="Checkmk"))
admin.add_view(CheckmkGroupRuleView(CheckmkGroupRule, \
                                    name="Manage Host-/Contact-/Service- Groups", category="Checkmk"))


from application.modules.checkmk.models import CheckmkRuleMngmt
from application.modules.checkmk.views import CheckmkMngmtRuleView
admin.add_view(CheckmkMngmtRuleView(CheckmkRuleMngmt, \
                                    name="Manage Checkmk Setup Rules", category="Checkmk"))

from application.modules.checkmk.models import CheckmkTagMngmt
from application.modules.checkmk.views import CheckmkTagMngmtView
admin.add_view(CheckmkTagMngmtView(CheckmkTagMngmt, name="Manage Hosttags", category="Checkmk"))

from application.modules.checkmk.models import CheckmkUserMngmt
from application.modules.checkmk.views import CheckmkUserMngmtView
admin.add_view(CheckmkUserMngmtView(CheckmkUserMngmt, name="Manage Checkmk Users", category="Checkmk"))

from application.modules.checkmk.models import CheckmkDowntimeRule
from application.modules.checkmk.views import CheckmkDowntimeView
admin.add_view(CheckmkDowntimeView(CheckmkDowntimeRule, name="Manage Downtimes", category="Checkmk"))


from application.modules.checkmk.models import CheckmkDCDRule
from application.modules.checkmk.views import CheckmkDCDView
admin.add_view(CheckmkDCDView(CheckmkDCDRule, name="Manage DCD Rules", category="Checkmk"))

from application.modules.checkmk.models import CheckmkPassword
from application.modules.checkmk.views import CheckmkPasswordView
admin.add_view(CheckmkPasswordView(CheckmkPassword, name="Manage Password Store", category="Checkmk"))

admin.add_sub_category(name="Manage Business Intelligence", parent_name="Checkmk")
from application.modules.checkmk.models import CheckmkBiAggregation, CheckmkBiRule
from application.modules.checkmk.views import CheckmkBiRuleView
admin.add_view(CheckmkBiRuleView(CheckmkBiAggregation, name="BI Aggregation",\
                                                            category="Manage Business Intelligence"))
admin.add_view(CheckmkBiRuleView(CheckmkBiRule, name="BI Rule", category="Manage Business Intelligence"))


from application.modules.checkmk.models import CheckmkFolderPool
from application.modules.checkmk.views import CheckmkFolderPoolView
admin.add_view(CheckmkFolderPoolView(CheckmkFolderPool, name="Folder Pools", category="Checkmk"))

from application.modules.checkmk.views import CheckmkInventorizeAttributesView
from application.modules.checkmk.models import CheckmkInventorizeAttributes
admin.add_view(CheckmkInventorizeAttributesView(CheckmkInventorizeAttributes, name="Inventorize from Checkmk Settings",
                                                            category="Checkmk"))

from application.modules.checkmk.models import CheckmkObjectCache
from application.modules.checkmk.views import CheckmkCacheView

admin.add_view(CheckmkCacheView(CheckmkObjectCache, \
                                    name="Cache", category="Checkmk"))

admin.add_sub_category(name="Checkmk Server", parent_name="Checkmk")
from application.modules.checkmk.models import CheckmkSettings, CheckmkSite
from application.modules.checkmk.views import CheckmkSettingsView, CheckmkSiteView
admin.add_view(CheckmkSettingsView(CheckmkSettings, name="Checkmk Site Updates and Creation", \
                                                            category="Checkmk Server"))
admin.add_view(CheckmkSiteView(CheckmkSite, name="Site Settings", category="Checkmk Server"))


from application.models.account import Account
from application.views.account import AccountModelView, ChildAccountModelView
admin.add_category(name="Accounts")
admin.add_view(AccountModelView(Account, name="Accounts", category="Accounts"))
admin.add_view(ChildAccountModelView(Account, name="Config Childs", endpoint='account_childs', category="Accounts"))

from application.models.cron import CronGroup, CronStats
from application.views.cron import CronStatsView, CronGroupView
admin.add_view(CronGroupView(CronGroup, name="Cronjob Group", category="Cronjobs"))
admin.add_view(CronStatsView(CronStats, name="State Table", category="Cronjobs"))

if os.path.exists(app.config['FILEADMIN_PATH']):
    admin.add_view(FileAdmin(app.config['FILEADMIN_PATH'], name="Filemanager"))

from application.modules.log.models import LogEntry
from application.modules.log.views import LogView
admin.add_view(LogView(LogEntry, name="Log"))

#.
#   .-- i-doit
admin.add_sub_category(name="i-doit", parent_name="Modules")

from application.modules.idoit.views import IdoitCustomAttributesView
from application.modules.idoit.models import IdoitCustomAttributes, \
                                            IdoitRewriteAttributeRule
admin.add_view(RewriteAttributeView(IdoitRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="i-doit"))
admin.add_view(IdoitCustomAttributesView(IdoitCustomAttributes,\
                                    name="Custom Attributes", category="i-doit"))
#.
#   .-- Netbox
admin.add_sub_category(name="Netbox", parent_name="Modules")

from application.modules.netbox.views import (
                                            NetboxCustomAttributesView,
                                            NetboxDataFlowAttributesView,
                                            NetboxDataFlowModelView,
                                        )
from application.modules.netbox.models import (
                                            NetboxCustomAttributes,
                                            NetboxRewriteAttributeRule,
                                            NetboxIpamIpaddressattributes,
                                            NetboxDcimInterfaceAttributes,
                                            NetboxContactAttributes,
                                            NetboxDataflowAttributes,
                                            NetboxDataflowModels,
                                            NetboxClusterAttributes,
                                            NetboxVirtualMachineAttributes,
                                            NetboxIpamPrefixAttributes,
                                            NetboxVirtualizationInterfaceAttributes,
                                        )
admin.add_view(RewriteAttributeView(NetboxRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="Netbox"))

admin.add_view(NetboxCustomAttributesView(NetboxCustomAttributes,\
        name="DCIM: Devices", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxDcimInterfaceAttributes,\
        name="DCIM: Interfaces", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxIpamIpaddressattributes,\
        name="IPAM: IP Addresses", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxIpamPrefixAttributes,\
        name="IPAM: Prefix", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxClusterAttributes,\
        name="Virtualization: Cluster", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxVirtualMachineAttributes,\
        name="Virtualization: Virtual Machines", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxVirtualizationInterfaceAttributes,\
        name="Virtualization: Interfaces", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxContactAttributes,\
        name="Tenancy: Contacts", category="Netbox"))

admin.add_sub_category(name="Plugin: Dataflow", parent_name="Netbox")
admin.add_view(NetboxDataFlowModelView(NetboxDataflowModels,\
        name="Model Defintion", category="Plugin: Dataflow"))

admin.add_view(NetboxDataFlowAttributesView(NetboxDataflowAttributes,\
        name="Field Definition", category="Plugin: Dataflow"))
#.
#   .-- VMware
admin.add_sub_category(name="VMware", parent_name="Modules")

from application.modules.vmware.models import VMwareRewriteAttributes, VMwareCustomAttributes
from application.modules.vmware.views import VMwareCustomAttributeView
admin.add_view(RewriteAttributeView(VMwareRewriteAttributes, name="Rewrite Attributes",
                                                            category="VMware"))
admin.add_view(VMwareCustomAttributeView(VMwareCustomAttributes, name="Custom Attributes",
                                                            category="VMware"))
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
