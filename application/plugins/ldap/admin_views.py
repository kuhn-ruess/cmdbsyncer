#!/usr/bin/env python3
"""
Flask-Admin view registration for the LDAP plugin.
"""
from application.views.module_overview import register_module_menu

from .views import LdapSearchView


def register_admin_views(admin):
    """Register all Flask-Admin views."""
    admin.add_sub_category(name="LDAP", parent_name="Modules")
    register_module_menu(admin, "LDAP")
    admin.add_view(LdapSearchView(name="Search Directory", category="LDAP",
                                  endpoint="ldap_search",
                                  menu_icon_type='fa',
                                  menu_icon_value='fa-search'))
