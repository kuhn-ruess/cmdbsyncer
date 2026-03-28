from application.modules.rule.views import RewriteAttributeView

from .models import VMwareRewriteAttributes, VMwareCustomAttributes
from .views import VMwareCustomAttributeView

def register_admin_views(admin):
    """Register Flask-Admin views for the VMware plugin."""

    admin.add_sub_category(name="VMware", parent_name="Modules")

    admin.add_view(RewriteAttributeView(VMwareRewriteAttributes, name="Rewrite Attributes",
                                                                category="VMware",
                                                                menu_icon_type='fa',
                                                                menu_icon_value='fa-exchange'))
    admin.add_view(VMwareCustomAttributeView(VMwareCustomAttributes, name="Custom Attributes",
                                                                category="VMware",
                                                                menu_icon_type='fa',
                                                                menu_icon_value='fa-tags'))