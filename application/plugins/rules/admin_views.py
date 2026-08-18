"""
Flask-Admin view registration for the Syncer Rules plugin.
"""
from application.views.module_overview import register_module_menu
from .models import SyncerRuleAutomation
from .views import SyncerRuleAutomationView

def register_admin_views(admin):
    """Register all Flask-Admin views that belong to the plugin."""
    admin.add_sub_category(name="Syncer Rules", parent_name="Modules")
    register_module_menu(admin, "Syncer Rules")

    admin.add_view(
        SyncerRuleAutomationView(
            SyncerRuleAutomation,
            name="Automate Syncer Rule Creation",
            category="Syncer Rules",
            menu_icon_type='fa',
            menu_icon_value='fa-rocket',
        )
    )
