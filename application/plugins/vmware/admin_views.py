from application.modules.rule.views import RewriteAttributeView

from .models import VMwareRewriteAttributes, VMwareCustomAttributes
from .views import VMwareCustomAttributeView

def register_admin_views(admin):
    """Register Flask-Admin views for the VMware plugin."""

    admin.add_sub_category(name="VMware", parent_name="Modules")

    admin.add_view(RewriteAttributeView(VMwareRewriteAttributes, name="Rewrite Attributes",
                                                                category="VMware"))
    admin.add_view(VMwareCustomAttributeView(VMwareCustomAttributes, name="Custom Attributes",
                                                                category="VMware"))