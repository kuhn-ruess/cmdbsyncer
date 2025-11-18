#!/usr/bin/env python3

from application.modules.rule.views import RewriteAttributeView
from .views import IdoitCustomAttributesView
from .models import IdoitCustomAttributes, IdoitRewriteAttributeRule

def register_admin_views(admin):
    """Register all Flask-Admin views."""
    admin.add_sub_category(name="i-doit", parent_name="Modules")
    admin.add_view(RewriteAttributeView(IdoitRewriteAttributeRule, name="Rewrite Attributes",
                                                                category="i-doit"))
    admin.add_view(IdoitCustomAttributesView(IdoitCustomAttributes,\
                                    name="Custom Attributes", category="i-doit"))
