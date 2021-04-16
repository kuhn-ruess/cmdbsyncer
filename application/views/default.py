"""
Default Model Views
"""
from flask_admin.contrib.mongoengine import ModelView

class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """
    can_export = True

