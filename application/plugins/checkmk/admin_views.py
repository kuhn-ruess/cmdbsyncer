"""
Flask-Admin view registrations for the Checkmk plugin.

This module keeps all admin registration logic out of the package __init__
to avoid heavy imports during package loading.
"""

from application.modules.rule.views import FiltereModelView, RewriteAttributeView

from .models import (
    CheckmkBiAggregation,
    CheckmkBiRule,
    CheckmkDCDRule,
    CheckmkDowntimeRule,
    CheckmkFilterRule,
    CheckmkFolderPool,
    CheckmkInventorizeAttributes,
    CheckmkNotificationRule,
    CheckmkObjectCache,
    CheckmkPassword,
    CheckmkRewriteAttributeRule,
    CheckmkRule,
    CheckmkRuleMngmt,
    CheckmkSettings,
    CheckmkSite,
    CheckmkTagMngmt,
    CheckmkUserMngmt,
    CheckmkGroupRule,
)

from .views import (
    CheckmkBiRuleView,
    CheckmkCacheView,
    CheckmkDCDView,
    CheckmkDowntimeView,
    CheckmkFolderPoolView,
    CheckmkInventorizeAttributesView,
    CheckmkMngmtRuleView,
    CheckmkNotificationRuleView,
    CheckmkPasswordView,
    CheckmkRuleView,
    CheckmkSettingsView,
    CheckmkSiteView,
    CheckmkTagMngmtView,
    CheckmkUserMngmtView,
    CheckmkGroupRuleView,
)


def register_admin_views(admin):
    """Register all Flask-Admin views that belong to the Checkmk plugin."""
    admin.add_sub_category(name="Checkmk", parent_name="Modules")

    admin.add_view(
        RewriteAttributeView(
            CheckmkRewriteAttributeRule,
            name="Rewrite and Create Custom Syncer Attributes",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-exchange',
        )
    )
    admin.add_view(
        FiltereModelView(
            CheckmkFilterRule,
            name="Filter Hosts and Whiteliste Checkmk Labels",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-filter',
        )
    )
    admin.add_view(
        CheckmkRuleView(
            CheckmkRule,
            name="Set Folder and  Attributes of Host",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-folder',
        )
    )
    admin.add_view(
        CheckmkGroupRuleView(
            CheckmkGroupRule,
            name="Manage Host-/Contact-/Service- Groups",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-users',
        )
    )
    admin.add_view(
        CheckmkMngmtRuleView(
            CheckmkRuleMngmt,
            name="Manage Checkmk Setup Rules",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-cogs',
        )
    )
    admin.add_view(
        CheckmkTagMngmtView(
            CheckmkTagMngmt,
            name="Manage Hosttags",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-tags',
        )
    )
    admin.add_view(
        CheckmkUserMngmtView(
            CheckmkUserMngmt,
            name="Manage Checkmk Users",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-user-circle',
        )
    )
    admin.add_view(
        CheckmkDowntimeView(
            CheckmkDowntimeRule,
            name="Manage Downtimes",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-calendar-times-o',
        )
    )
    admin.add_view(
        CheckmkNotificationRuleView(
            CheckmkNotificationRule,
            name="Manage Notification Rules",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-bell',
        )
    )
    admin.add_view(
        CheckmkDCDView(
            CheckmkDCDRule,
            name="Manage DCD Rules",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-refresh',
        )
    )
    admin.add_view(
        CheckmkPasswordView(
            CheckmkPassword,
            name="Manage Password Store",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-lock',
        )
    )

    admin.add_sub_category(name="Manage Business Intelligence", parent_name="Checkmk")
    admin.add_view(
        CheckmkBiRuleView(
            CheckmkBiAggregation,
            name="BI Aggregation",
            category="Manage Business Intelligence",
            menu_icon_type='fa',
            menu_icon_value='fa-sitemap',
        )
    )
    admin.add_view(
        CheckmkBiRuleView(
            CheckmkBiRule,
            name="BI Rule",
            category="Manage Business Intelligence",
            menu_icon_type='fa',
            menu_icon_value='fa-sitemap',
        )
    )

    admin.add_view(
        CheckmkFolderPoolView(
            CheckmkFolderPool,
            name="Folder Pools",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-folder-open',
        )
    )
    admin.add_view(
        CheckmkInventorizeAttributesView(
            CheckmkInventorizeAttributes,
            name="Inventorize from Checkmk Settings",
            category="Checkmk",
            menu_icon_type='fa',
            menu_icon_value='fa-database',
        )
    )
    admin.add_view(
        CheckmkCacheView(CheckmkObjectCache, name="Cache", category="Checkmk",
                        menu_icon_type='fa', menu_icon_value='fa-th')
    )

    admin.add_sub_category(name="Checkmk Server", parent_name="Checkmk")
    admin.add_view(
        CheckmkSettingsView(
            CheckmkSettings,
            name="Checkmk Site Updates and Creation",
            category="Checkmk Server",
            menu_icon_type='fa',
            menu_icon_value='fa-cogs',
        )
    )
    admin.add_view(
        CheckmkSiteView(
            CheckmkSite,
            name="Site Settings",
            category="Checkmk Server",
            menu_icon_type='fa',
            menu_icon_value='fa-building',
        )
    )
