#!/usr/bin/env python3
"""
External documentation URLs referenced from admin forms.

Each view adds a "Documentation" pill to its form_rules pointing at
the matching page on docs.cmdbsyncer.de — keep this dict in sync
with the structure at https://docs.cmdbsyncer.de/.
"""

docu_links = {
    'rewrite' : 'https://docs.cmdbsyncer.de/basics/rewrite_attributes/',
    'accounts' : 'https://docs.cmdbsyncer.de/basics/accounts/',
    'cmk_inventory_attributes': 'https://docs.cmdbsyncer.de/checkmk/inventorize/',
    'cmk_groups': 'https://docs.cmdbsyncer.de/checkmk/groups_management/',
    'cmk_setup_rules': 'https://docs.cmdbsyncer.de/checkmk/rules_management/',
    'cmk_hosttags': 'https://docs.cmdbsyncer.de/checkmk/create_hosttags/',
    'cmk_password_store': 'https://docs.cmdbsyncer.de/checkmk/password_store/',

    # Enterprise features — referenced from cmdbsyncer_enterprise views.
    'ent_overview': 'https://docs.cmdbsyncer.de/enterprise/',
    'ent_remote_user_sso': 'https://docs.cmdbsyncer.de/enterprise/remote_user_sso/',
    'ent_ldap_login': 'https://docs.cmdbsyncer.de/enterprise/ldap_login/',
    'ent_oidc_login': 'https://docs.cmdbsyncer.de/enterprise/oidc_login/',
    'ent_secrets_manager': 'https://docs.cmdbsyncer.de/enterprise/secrets_manager/',
    'ent_json_logging': 'https://docs.cmdbsyncer.de/enterprise/json_logging/',
    'ent_audit_log': 'https://docs.cmdbsyncer.de/enterprise/audit_log/',
    'ent_notifications': 'https://docs.cmdbsyncer.de/enterprise/notifications/',
    'ent_webhook_signatures': 'https://docs.cmdbsyncer.de/enterprise/webhook_signatures/',
    'ent_prometheus_metrics': 'https://docs.cmdbsyncer.de/enterprise/prometheus_metrics/',
    'ent_scheduled_backup': 'https://docs.cmdbsyncer.de/enterprise/scheduled_backup/',
    'ent_approval_workflow': 'https://docs.cmdbsyncer.de/enterprise/approval_workflow/',
}
