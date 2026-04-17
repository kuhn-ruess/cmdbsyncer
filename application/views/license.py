"""
License Information View
"""
import importlib.util
from datetime import datetime
from flask_admin import BaseView, expose
from flask_login import current_user

from application import enterprise
from application.enterprise import run_hook


class LicenseView(BaseView):
    """
    Show Enterprise License Information
    """

    def is_accessible(self):
        return current_user.is_authenticated

    @expose('/')
    def index(self):
        """
        Render license info page
        """
        info = run_hook('license_info')
        exp_ts = info.get('exp') if info else None
        exp_human = datetime.fromtimestamp(exp_ts).strftime('%Y-%m-%d %H:%M:%S') \
            if isinstance(exp_ts, (int, float)) else None
        package_installed = importlib.util.find_spec('cmdbsyncer_enterprise') is not None
        registry_features = sorted(enterprise._features)
        registry_hooks = sorted(enterprise._hooks.keys())
        return self.render('license_info.html',
                           license=info,
                           exp_human=exp_human,
                           package_installed=package_installed,
                           load_status=enterprise.load_status,
                           registry_features=registry_features,
                           registry_hooks=registry_hooks)
