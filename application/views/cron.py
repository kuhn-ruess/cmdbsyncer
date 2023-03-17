"""
Cron Model View
"""
# pylint: disable=too-few-public-methods
from datetime import datetime
from flask_login import current_user

from application.views.default import DefaultModelView


def format_date(v, c, m, p):
    """ Format Date Field"""
    return datetime.strftime(getattr(m,p), "%d.%m.%Y %H:%M")




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

    column_formatters = {
        'next_run': format_date,
        'last_run': format_date,
        'last_start': format_date,
        'last_ended': format_date,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
