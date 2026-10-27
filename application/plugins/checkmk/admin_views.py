"""
Flask-Admin view registrations for the Checkmk plugin.

This module keeps all admin registration logic out of the package __init__
to avoid heavy imports during package loading.
"""

from application.modules.rule.views import FiltereModelView, RewriteAttributeView
from application.views.menu_links import AccessMenuLink
from application.views.module_overview import register_module_menu

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
    CheckmkRewriteAttributeRule,
    CheckmkRule,
    CheckmkRuleMngmt,
    CheckmkSettings,
    CheckmkSite,
    CheckmkSitePool,
    CheckmkTagMngmt,
    CheckmkGroupRule,
)

from .user_models import (
    CheckmkUserMngmt,
    CheckmkUserGenerationRule,
)
from .ldap_models import CheckmkLdapConnection
from .ldap_views import CheckmkLdapConnectionView

from .views import (
    CheckmkBiRuleView,
    CheckmkCacheView,
    CheckmkConfigChecksView,
    CheckmkDataQualityView,
    CheckmkFolderView,
    CheckmkRuleOptimizationView,
    CheckmkDCDView,
    CheckmkDowntimeView,
    CheckmkFolderPoolView,
    CheckmkInventorizeAttributesView,
    CheckmkMngmtRuleView,
    CheckmkNotificationRuleView,
    CheckmkRuleView,
    CheckmkSettingsView,
    CheckmkSiteView,
    CheckmkSitePoolView,
    CheckmkTagMngmtView,
    CheckmkTestFolderScopeView,
    CheckmkUserMngmtView,
    CheckmkUserGenerationRuleView,
    CheckmkUserGenerationPreviewView,
    CheckmkGroupRuleView,
)


def _shown(views):
    """True while at least one of the views is in this user's menu."""
    return any(view.is_accessible() and view.is_visible() for view in views)


def _add_divider(admin, above, below):
    """
    A divider in the Checkmk menu, shown only while there are entries on
    both sides of it, so it never floats at the top or the bottom or
    doubles up next to a group the user cannot see.
    """
    admin.add_link(AccessMenuLink(
        name='', url='#', category='Checkmk', class_name='dropdown-divider',
        access=lambda: _shown(above) and _shown(below)))


def register_admin_views(admin):
    """
    Register all Flask-Admin views that belong to the Checkmk plugin.

    Flask-Admin keeps the registration order, so the order below is the
    menu: what goes to the hosts in Checkmk, what else is created in
    Checkmk, the Checkmk sites and the way back, and at the bottom the
    read only views to check and debug the result.
    """
    admin.add_sub_category(name="Checkmk", parent_name="Modules")
    register_module_menu(admin, "Checkmk")
    above = []

    def add(group, view):
        admin.add_view(view)
        group.append(view)

    #   .-- Host export
    hosts = []
    add(hosts, RewriteAttributeView(
        CheckmkRewriteAttributeRule,
        name="Rewrite and Create Custom Syncer Attributes",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-exchange',
    ))
    add(hosts, FiltereModelView(
        CheckmkFilterRule,
        name="Filter Hosts and Whiteliste Checkmk Labels",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-filter',
    ))
    add(hosts, CheckmkRuleView(
        CheckmkRule,
        name="Set Folder and  Attributes of Host",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-folder',
    ))
    add(hosts, CheckmkTestFolderScopeView(
        name="Limit Host Export to Folders",
        category="Checkmk",
        endpoint="checkmk_test_folder_scope",
        menu_icon_type='fa',
        menu_icon_value='fa-folder-open',
    ))
    admin.add_sub_category(name="Pools", parent_name="Checkmk")
    add(hosts, CheckmkFolderPoolView(
        CheckmkFolderPool,
        name="Folder Pools",
        category="Pools",
        menu_icon_type='fa',
        menu_icon_value='fa-folder-open',
    ))
    add(hosts, CheckmkSitePoolView(
        CheckmkSitePool,
        name="Site Pools",
        category="Pools",
        menu_icon_type='fa',
        menu_icon_value='fa-server',
    ))
    above += hosts
    #.
    #   .-- Checkmk objects
    objects = []
    _add_divider(admin, list(above), objects)
    add(objects, CheckmkMngmtRuleView(
        CheckmkRuleMngmt,
        name="Manage Checkmk Setup Rules",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-cogs',
    ))
    add(objects, CheckmkGroupRuleView(
        CheckmkGroupRule,
        name="Manage Host-/Contact-/Service- Groups",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-users',
    ))
    add(objects, CheckmkTagMngmtView(
        CheckmkTagMngmt,
        name="Manage Hosttags",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-tags',
    ))
    add(objects, CheckmkUserMngmtView(
        CheckmkUserMngmt,
        name="Manage Checkmk Users",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-user-circle',
    ))
    add(objects, CheckmkUserGenerationRuleView(
        CheckmkUserGenerationRule,
        name="Generate Checkmk Users",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-user-plus',
    ))
    add(objects, CheckmkLdapConnectionView(
        CheckmkLdapConnection,
        name="Manage LDAP Connections",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-address-book',
    ))
    add(objects, CheckmkDowntimeView(
        CheckmkDowntimeRule,
        name="Manage Downtimes",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-calendar-times-o',
    ))
    add(objects, CheckmkNotificationRuleView(
        CheckmkNotificationRule,
        name="Manage Notification Rules",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-bell',
    ))
    add(objects, CheckmkDCDView(
        CheckmkDCDRule,
        name="Manage DCD Rules",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-refresh',
    ))
    admin.add_sub_category(name="Manage Business Intelligence", parent_name="Checkmk")
    add(objects, CheckmkBiRuleView(
        CheckmkBiAggregation,
        name="BI Aggregation",
        category="Manage Business Intelligence",
        menu_icon_type='fa',
        menu_icon_value='fa-sitemap',
    ))
    add(objects, CheckmkBiRuleView(
        CheckmkBiRule,
        name="BI Rule",
        category="Manage Business Intelligence",
        menu_icon_type='fa',
        menu_icon_value='fa-sitemap',
    ))
    above += objects
    #.
    #   .-- Sites and the way back
    sites = []
    _add_divider(admin, list(above), sites)
    admin.add_sub_category(name="Checkmk Server", parent_name="Checkmk")
    add(sites, CheckmkSettingsView(
        CheckmkSettings,
        name="Checkmk Site Updates and Creation",
        category="Checkmk Server",
        menu_icon_type='fa',
        menu_icon_value='fa-cogs',
    ))
    add(sites, CheckmkSiteView(
        CheckmkSite,
        name="Site Settings",
        category="Checkmk Server",
        menu_icon_type='fa',
        menu_icon_value='fa-building',
    ))
    add(sites, CheckmkInventorizeAttributesView(
        CheckmkInventorizeAttributes,
        name="Inventorize from Checkmk Settings",
        category="Checkmk",
        menu_icon_type='fa',
        menu_icon_value='fa-database',
    ))
    above += sites
    #.
    #   .-- Check and debug
    checks = []
    _add_divider(admin, list(above), checks)
    add(checks, CheckmkFolderView(
        name="Folders and Folder Options",
        category="Checkmk",
        endpoint="checkmk_folders",
        menu_icon_type='fa',
        menu_icon_value='fa-folder',
    ))
    add(checks, CheckmkUserGenerationPreviewView(
        name="Preview Generated Users",
        category="Checkmk",
        endpoint="checkmk_user_generation_preview",
        menu_icon_type='fa',
        menu_icon_value='fa-eye',
    ))
    admin.add_sub_category(name="Data Quality", parent_name="Checkmk")
    add(checks, CheckmkDataQualityView(
        name="Data Quality Check",
        category="Data Quality",
        endpoint="checkmk_data_quality",
        menu_icon_type='fa',
        menu_icon_value='fa-check-square-o',
    ))
    add(checks, CheckmkConfigChecksView(
        name="Configuration Checks",
        category="Data Quality",
        endpoint="checkmk_config_checks",
        menu_icon_type='fa',
        menu_icon_value='fa-stethoscope',
    ))
    add(checks, CheckmkCacheView(
        CheckmkObjectCache, name="Cache", category="Checkmk",
        menu_icon_type='fa', menu_icon_value='fa-th',
    ))
    #.
    # Reachable from the Setup Rules list, not from the menu: it is a
    # tool for those rules, not a place of its own.
    admin.add_view(
        CheckmkRuleOptimizationView(
            name="Rule Optimization",
            endpoint="checkmk_rule_optimization",
        )
    )
