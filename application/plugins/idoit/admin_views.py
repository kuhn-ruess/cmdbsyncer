#!/usr/bin/env python3
"""
Flask-Admin view registration for the i-doit plugin.
"""
from application.views.module_overview import register_module_menu
from application.modules.rule.views import RewriteAttributeView
from .views import IdoitCustomAttributesView
from .models import IdoitCustomAttributes, IdoitRewriteAttributeRule

def register_admin_views(admin):
    """Register all Flask-Admin views."""
    admin.add_sub_category(name="i-doit", parent_name="Modules")
    register_module_menu(admin, "i-doit")
    admin.add_view(RewriteAttributeView(IdoitRewriteAttributeRule, name="Rewrite Attributes",
                                                                category="i-doit",
                                                                menu_icon_type='fa',
                                                                menu_icon_value='fa-exchange'))
    admin.add_view(IdoitCustomAttributesView(IdoitCustomAttributes,\
                                    name="Custom Attributes", category="i-doit",
                                    menu_icon_type='fa',
                                    menu_icon_value='fa-tags'))
