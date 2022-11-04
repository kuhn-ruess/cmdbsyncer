""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
import os
from flask import Flask, url_for
from flask_admin import Admin
from flask_admin.menu import MenuLink
from flask_login import LoginManager
from flask_mail import Mail
from flask_bootstrap import Bootstrap
from flask_mongoengine import MongoEngine
from application.modules.log import Log


VERSION = '3.0.0-wip'


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


try:
    db = MongoEngine()
    from uwsgidecorators import postfork

    @postfork
    def setup_db():
        """db init in uwsgi"""
        db.init_app(app)
except ImportError:
    db = MongoEngine(app)


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

from application.modules.rule.views import FiltereModelView, RewriteLabelView


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
from application.modules.custom_labels.models import CustomLabelRule
from application.modules.custom_labels.views import CustomLabelView
admin.add_view(CustomLabelView(CustomLabelRule, name="Custom Labels", category="Rules"))
#.
#   .-- Checkmk
admin.add_sub_category(name="Checkmk", parent_name="Rules")
from application.modules.checkmk.models import CheckmkRule, CheckmkGroupRule, CheckmkFilterRule
from application.modules.checkmk.views import CheckmkRuleView, CheckmkGroupRuleView


from application.modules.checkmk.models import CheckmkRewriteLabelRule
admin.add_view(RewriteLabelView(CheckmkRewriteLabelRule, name="Rewrite Attributes",
                                                            category="Checkmk"))
admin.add_view(FiltereModelView(CheckmkFilterRule, name="Filter", category="Checkmk"))
admin.add_view(CheckmkRuleView(CheckmkRule, name="Export Rules", category="Checkmk"))
admin.add_view(CheckmkGroupRuleView(CheckmkGroupRule, name="Group Mananagemt", category="Checkmk"))

from application.modules.checkmk.models import CheckmkFolderPool
from application.modules.checkmk.views import CheckmkFolderPoolView
admin.add_view(CheckmkFolderPoolView(CheckmkFolderPool, name="Folder Pools", category="Checkmk"))
#.
#   .-- Ansible
admin.add_sub_category(name="Ansible", parent_name="Rules")
from application.modules.ansible.models import AnsibleCustomVariablesRule, AnsibleFilterRule, AnsibleRewriteAttributesRule
from application.modules.ansible.views import AnsibleCustomVariablesView

admin.add_view(RewriteLabelView(AnsibleRewriteAttributesRule, name="Rewrite Attributes",
                                                            category="Ansible"))
admin.add_view(FiltereModelView(AnsibleFilterRule, name="Filter", category="Ansible"))
admin.add_view(AnsibleCustomVariablesView(AnsibleCustomVariablesRule,\
                                    name="Custom Variables", category="Ansible"))
#.
#   .-- Netbox
admin.add_sub_category(name="Netbox", parent_name="Rules")

from application.modules.netbox.views import NetboxCustomAttributesView
from application.modules.netbox.models import NetboxCustomAttributes, NetboxRewriteLabelRule,\
                                              NetboxFilterRule
admin.add_view(RewriteLabelView(NetboxRewriteLabelRule, name="Rewrite Attributes",
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
#.
