"""Flask-Admin registration for the Jira Cloud Export views."""
from application.modules.rule.views import RewriteAttributeView

from .views import (
    JiraCloudFilterView,
    JiraExportRuleView,
    JiraSchemaCacheView,
)
from .models import (
    JiraCloudFilterRule,
    JiraCloudRewriteAttributeRule,
    JiraExportRule,
    JiraSchemaCache,
)


def register_admin_views(admin):
    """Register the Jira Cloud submenu."""
    admin.add_sub_category(name="Jira Cloud", parent_name="Modules")

    admin.add_view(JiraCloudFilterView(
        JiraCloudFilterRule,
        name="Filter", category="Jira Cloud",
        menu_icon_type='fa', menu_icon_value='fa-filter'))

    admin.add_view(RewriteAttributeView(
        JiraCloudRewriteAttributeRule,
        name="Rewrite Attributes", category="Jira Cloud",
        menu_icon_type='fa', menu_icon_value='fa-exchange'))

    admin.add_view(JiraExportRuleView(
        JiraExportRule,
        name="Export Rules", category="Jira Cloud",
        menu_icon_type='fa', menu_icon_value='fa-upload'))

    admin.add_view(JiraSchemaCacheView(
        JiraSchemaCache,
        name="Schema Cache", category="Jira Cloud",
        menu_icon_type='fa', menu_icon_value='fa-database'))
