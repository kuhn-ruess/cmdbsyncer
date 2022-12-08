""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
import os
from datetime import datetime
from pprint import pformat
from flask import Flask, url_for
from flask_admin import Admin
from flask_admin.menu import MenuLink
from flask_login import LoginManager
from flask_mail import Mail
from flask_bootstrap import Bootstrap
from flask_mongoengine import MongoEngine


VERSION = '3.0.0-pre3'

app = Flask(__name__)
env = os.environ.get('config')
if env == "prod":
    app.config.from_object('application.config.ProductionConfig')
elif env == "compose":
    app.config.from_object('application.config.ComposeConfig')
else:
    app.config.from_object('application.config.BaseConfig')
    app.jinja_env.auto_reload = True
if app.config['DEBUG']:
    print(f"Loaded Config: {env}")

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

from plugins import *
from application.plugins import *

from application.views.default import IndexView, DefaultModelView

from application.auth.views import AUTH
app.register_blueprint(AUTH)

from application.modules.rule.views import FiltereModelView, RewriteAttributeView


from application.api.views import API_BP as api
app.register_blueprint(api, url_prefix="/api/v1")

admin = Admin(app, name=f"CMDB Syncer {VERSION}",
                   template_mode='bootstrap4', index_view=IndexView())


#   .-- Host
from application.models.host import Host
from application.views.host import HostModelView
admin.add_view(HostModelView(Host, name="Hosts"))
#.
#   .-- Global
from application.modules.custom_attributes.models import CustomAttributeRule
from application.modules.custom_attributes.views import CustomAttributeView
admin.add_view(CustomAttributeView(CustomAttributeRule, name="Custom Attributes", category="Rules"))
#.
#   .-- Checkmk
admin.add_sub_category(name="Checkmk", parent_name="Rules")
from application.modules.checkmk.models import CheckmkRule, CheckmkGroupRule, CheckmkFilterRule
from application.modules.checkmk.views import CheckmkRuleView, CheckmkGroupRuleView


from application.modules.checkmk.models import CheckmkRewriteAttributeRule
admin.add_view(RewriteAttributeView(CheckmkRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="Checkmk"))
admin.add_view(FiltereModelView(CheckmkFilterRule, name="Filter", category="Checkmk"))
admin.add_view(CheckmkRuleView(CheckmkRule, name="CMK Export Rules", category="Checkmk"))
admin.add_view(CheckmkGroupRuleView(CheckmkGroupRule, \
                                    name="CMK Groups Mananagemt", category="Checkmk"))

from application.modules.checkmk.models import CheckmkRuleMngmt
from application.modules.checkmk.views import CheckmkMngmtRuleView
admin.add_view(CheckmkMngmtRuleView(CheckmkRuleMngmt, \
                                    name="CMK Rules Mananagemt", category="Checkmk"))

from application.modules.checkmk.models import CheckmkFolderPool
from application.modules.checkmk.views import CheckmkFolderPoolView
admin.add_view(CheckmkFolderPoolView(CheckmkFolderPool, name="Folder Pools", category="Checkmk"))
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
                                                NetboxRewriteAttributeRule, NetboxFilterRule
admin.add_view(RewriteAttributeView(NetboxRewriteAttributeRule, name="Rewrite Attributes",
                                                            category="Netbox"))
admin.add_view(FiltereModelView(NetboxFilterRule, name="Filter", category="Netbox"))
admin.add_view(NetboxCustomAttributesView(NetboxCustomAttributes,\
                                    name="Custom Attributes", category="Netbox"))
#.
#   .-- Rest
from application.models.account import Account
from application.views.account import AccountModelView
admin.add_view(AccountModelView(Account, name="Accounts", category="Config"))

from application.models.user import User
from application.views.user import UserView
admin.add_view(UserView(User, category='Config'))

from application.models.config import Config
from application.views.config import ConfigModelView

admin.add_view(ConfigModelView(Config, name="System Config", category="Config"))

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
