""" Main entry """
# pylint: disable=invalid-name
# pylint: disable=wrong-import-position
# pylint: disable=ungrouped-imports
import os
from flask import Flask
from flask_admin import Admin
from flask_mongoengine import MongoEngine
from application.modules.log import Log


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
    print("   \033[91mWARNING: STANDALONE MODE - NOT FOR PROD\033[0m")
    print(" * HINT: uwsgi modul not loaded")
    db = MongoEngine(app)

log = Log()


source_register = [
   (lambda: False, "Not set")
]

from application.sync_modules import *


from application.models.host import Host
from application.views.host import HostModelView

from application.models.account import Account
from application.views.account import AccountModelView

admin = Admin(app, name="CMDB Sync", template_mode='bootstrap4')

admin.add_view(HostModelView(Host, name="Hosts"))

admin.add_view(AccountModelView(Account, name="Accounts", category="Config"))
