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


VERSION = '1.3.2'


app = Flask(__name__)
if os.environ.get('env') == "prod":
    app.config.from_object('application.config.ProductionConfig')
else:
    app.config.from_object('application.config.BaseConfig')
    app.jinja_env.auto_reload = True


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

from application.views.default import IndexView


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

from application.models.folder_pool import FolderPool
from application.views.folder_pool import FolderPoolModelView

admin = Admin(app, name="CMDB Syncer 1.3.2", template_mode='bootstrap4', index_view=IndexView())

admin.add_view(HostModelView(Host, name="Hosts"))

admin.add_view(RuleModelView(LabelRule, name="Label Rules", category="Rules"))
admin.add_view(RuleModelView(HostRule, name="Custom Host Rules", category="Rules"))
admin.add_view(RuleModelView(ActionRule, name="Action Rules", category="Rules"))

admin.add_view(FolderPoolModelView(FolderPool, name="Folder Pools", category="Config"))
admin.add_view(AccountModelView(Account, name="Accounts", category="Config"))
admin.add_view(UserView(User, category='Config'))
admin.add_link(MenuLink(name='Change Password', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}change-password"))
admin.add_link(MenuLink(name='Set 2FA Code', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}set-2fa"))
admin.add_link(MenuLink(name='Logout', category='Profil',
                        url=f"{app.config['BASE_PREFIX']}logout"))
