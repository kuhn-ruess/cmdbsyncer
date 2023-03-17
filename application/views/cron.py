"""
Cron Model View
"""
# pylint: disable=too-few-public-methods
import re
from mongoengine.errors import DoesNotExist
from flask_login import current_user
from flask_admin.actions import action
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter

from flask import flash
from flask import Markup

from application.views.default import DefaultModelView
from application.models.host import Host
from application.models.config import Config





class CronStatsView(DefaultModelView):
    """
    Cron Stats Model
    """
    can_edit = False
    can_create = False
    can_export = True

    export_types = ['xlsx', 'csv']

    page_size = 50
    can_set_page_size = True

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
