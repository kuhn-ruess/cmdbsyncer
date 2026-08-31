#!/usr/bin/env python3
"""
Flask-Admin view registration for the ServiceNow plugin.
"""
from application.views.module_overview import register_module_menu

from .views import ServiceNowQueryView


def register_admin_views(admin):
    """Register all Flask-Admin views."""
    admin.add_sub_category(name="ServiceNow", parent_name="Modules")
    register_module_menu(admin, "ServiceNow")
    admin.add_view(ServiceNowQueryView(name="Query Table", category="ServiceNow",
                                       endpoint="servicenow_query",
                                       menu_icon_type='fa',
                                       menu_icon_value='fa-search'))
