from .models import SyncerRuleAutomation
from .views import SyncerRuleAutomationView

def register_admin_views(admin):
    """Register all Flask-Admin views that belong to the plugin."""
    admin.add_sub_category(name="Syncer Rules", parent_name="Modules")

    admin.add_view(
        SyncerRuleAutomationView(
            SyncerRuleAutomation,
            name="Automate Syncer Rule Creation",
            category="Syncer Rules",
        )
    )