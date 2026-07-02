"""
Flask-Admin view registration for the Ansible plugin.
"""
# pylint: disable=too-few-public-methods
from .models import (
    AnsibleCustomVariablesRule,
    AnsibleFilterRule,
    AnsiblePlaybookFireRule,
    AnsibleProject,
    AnsibleRewriteAttributesRule,
    AnsibleRunStats,
)
from .views import (
    AnsibleCustomVariablesView,
    AnsibleFilterRuleView,
    AnsiblePlaybookFireRuleView,
    AnsiblePlaybookRunView,
    AnsibleProjectView,
    AnsibleRewriteRuleView,
    AnsibleRunStatsView,
)


def register_admin_views(admin):
    """
    Register Flask-Admin views for the Ansible plugin.

    Menu layout follows the workflow: the Projects hub first, then the two
    run actions, then all four rule types grouped under one 'Rules'
    sub-category (so no single rule type floats at the top level next to
    the actions).

      Ansible
        ├─ Projects        (hub — rules grouped per project)
        ├─ Run Playbook
        ├─ Run History
        └─ Rules
             ├─ Filter
             ├─ Rewrite Attributes
             ├─ Ansible Attributes
             └─ Playbook Fire Rules
    """
    admin.add_sub_category(name="Ansible", parent_name="Modules")

    admin.add_view(
        AnsibleProjectView(
            AnsibleProject,
            name="Projects",
            category="Ansible",
            menu_icon_type='fa',
            menu_icon_value='fa-folder',
        )
    )
    admin.add_view(
        AnsiblePlaybookRunView(
            name="Run Playbook",
            endpoint='ansibleplaybookrun',
            category="Ansible",
            menu_icon_type='fa',
            menu_icon_value='fa-play',
        )
    )
    admin.add_view(
        AnsibleRunStatsView(
            AnsibleRunStats,
            name="Run History",
            endpoint='ansiblerunstats',
            category="Ansible",
            menu_icon_type='fa',
            menu_icon_value='fa-history',
        )
    )

    admin.add_sub_category(name="Rules", parent_name="Ansible")
    admin.add_view(
        AnsibleFilterRuleView(
            AnsibleFilterRule,
            name="Filter",
            category="Rules",
            menu_icon_type='fa',
            menu_icon_value='fa-filter',
        )
    )
    admin.add_view(
        AnsibleRewriteRuleView(
            AnsibleRewriteAttributesRule,
            name="Rewrite Attributes",
            category="Rules",
            menu_icon_type='fa',
            menu_icon_value='fa-exchange',
        )
    )
    admin.add_view(
        AnsibleCustomVariablesView(
            AnsibleCustomVariablesRule,
            name="Ansible Attributes",
            category="Rules",
            menu_icon_type='fa',
            menu_icon_value='fa-tags',
        )
    )
    admin.add_view(
        AnsiblePlaybookFireRuleView(
            AnsiblePlaybookFireRule,
            name="Playbook Fire Rules",
            category="Rules",
            menu_icon_type='fa',
            menu_icon_value='fa-bolt',
        )
    )
