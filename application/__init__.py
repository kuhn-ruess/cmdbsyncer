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


VERSION = '2.1.2-dev'


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

source_register = [
   (lambda: False, "Not set")
]

from application.plugins_shipped import *
from application.plugins import *

from application.views.default import IndexView, DefaultModelView

from application.auth.views import AUTH
app.register_blueprint(AUTH)

from application.models.host import Host
from application.views.host import HostModelView

from application.models.account import Account
from application.views.account import AccountModelView

from application.models.user import User
from application.views.user import UserView

from application.models.rule import ActionRule, LabelRule, HostRule
from application.views.rule import RuleModelView

#from application.models.cmk_ruleset_rules import CmkRulesetRule
from application.models.cmk_group_rules import CmkGroupRule

from application.models.ansible_rule import AnsibleCustomVariables, AnsibleCustomVariablesRule

from application.models.folder_pool import FolderPool
from application.views.folder_pool import FolderPoolModelView

from application.api.views import API_BP as api
app.register_blueprint(api, url_prefix="/api/v1")

admin = Admin(app, name=f"CMDB Syncer {VERSION}",
                   template_mode='bootstrap4', index_view=IndexView())

admin.add_view(HostModelView(Host, name="Hosts"))

admin.add_view(RuleModelView(HostRule, name="Custom Label Rules", category="Rules"))
admin.add_view(RuleModelView(LabelRule, name="Label Cleanup/ Whitelist Rules", category="Rules"))

admin.add_sub_category(name="Checkmk Rules", parent_name="Rules")
admin.add_view(RuleModelView(ActionRule, name="Host Rules", category="Checkmk Rules"))
#admin.add_view(DefaultModelView(CmkRulesetRule, name="Ruleset Rules", category="Checkmk Rules"))
admin.add_view(DefaultModelView(CmkGroupRule, name="Group Rules", category="Checkmk Rules"))
admin.add_view(FolderPoolModelView(FolderPool, name="Folder Pools", category="Checkmk Rules"))

admin.add_sub_category(name="Ansible Rules", parent_name="Rules")
admin.add_view(RuleModelView(AnsibleCustomVariables,\
                                    name="Define Custom Variables by Labels", category="Ansible Rules"))
admin.add_view(RuleModelView(AnsibleCustomVariablesRule,\
                                    name="Define Custom Variables based on Custom Variables", category="Ansible Rules"))

admin.add_view(AccountModelView(Account, name="Accounts", category="Config"))
admin.add_view(UserView(User, category='Config'))
admin.add_link(MenuLink(name='Change Password', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}change-password"))
admin.add_link(MenuLink(name='Set 2FA Code', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}set-2fa"))
admin.add_link(MenuLink(name='Logout', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}logout"))
