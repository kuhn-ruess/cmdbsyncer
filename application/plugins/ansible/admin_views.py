from application.modules.rule.views import FiltereModelView, RewriteAttributeView

from .models import (
    AnsibleCustomVariablesRule,
    AnsibleFilterRule,
    AnsibleRewriteAttributesRule,
)
from .views import AnsibleCustomVariablesView


def register_admin_views(admin):
    """Register Flask-Admin views for the Ansible plugin."""
    admin.add_sub_category(name="Ansible", parent_name="Modules")

    admin.add_view(
        RewriteAttributeView(
            AnsibleRewriteAttributesRule,
            name="Rewrite Attributes",
            category="Ansible",
        )
    )
    admin.add_view(
        FiltereModelView(
            AnsibleFilterRule,
            name="Filter",
            category="Ansible",
        )
    )
    admin.add_view(
        AnsibleCustomVariablesView(
            AnsibleCustomVariablesRule,
            name="Ansible Attributes",
            category="Ansible",
        )
    )
