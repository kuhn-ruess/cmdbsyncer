"""
Flask-Admin view registration of Event Driven Ansible
"""
from application.views.module_overview import register_module_menu

from .models import EdaEventLog, EdaEventRule
from .views import EdaEventLogView, EdaEventRuleView


def register_admin_views(admin):
    """
    Event Driven Ansible
      ├─ Event Rules
      └─ Event History
    """
    admin.add_sub_category(name="Event Driven Ansible", parent_name="Modules")
    register_module_menu(admin, "Event Driven Ansible")
    admin.add_view(EdaEventRuleView(EdaEventRule, name="Event Rules",
                                    category="Event Driven Ansible",
                                    menu_icon_type='fa',
                                    menu_icon_value='fa-bolt'))
    admin.add_view(EdaEventLogView(EdaEventLog, name="Event History",
                                   endpoint='edaeventlog',
                                   category="Event Driven Ansible",
                                   menu_icon_type='fa',
                                   menu_icon_value='fa-history'))
