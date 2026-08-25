"""
Registry of rule types that can be imported/exported — maps a short
rule-type ident to its (module_path, model_class_name) or, when the
type is only a subset of a collection, to
(module_path, model_class_name, queryset_filter_kwargs).

Everything a user configures belongs in ``rules`` so a full export is a
complete configuration backup. Runtime state, caches and history are
listed in ``not_exported`` further down.
"""
rules = {
    'ansible_projects': ('application.plugins.ansible.models', 'AnsibleProject'),
    'ansible_customvars': ('application.plugins.ansible.models', 'AnsibleCustomVariablesRule'),
    'ansible_filter': ('application.plugins.ansible.models', 'AnsibleFilterRule'),
    'ansible_playbook_fire': ('application.plugins.ansible.models', 'AnsiblePlaybookFireRule'),
    'ansible_rewrite': ('application.plugins.ansible.models', 'AnsibleRewriteAttributesRule'),
    'custom_attributes': ('application.modules.custom_attributes.models', 'CustomAttributeRule'),
    'cmk_tags': ('application.plugins.checkmk.models', 'CheckmkTagMngmt'),
    'cmk_filter': ('application.plugins.checkmk.models', 'CheckmkFilterRule'),
    'cmk_inventory': ('application.plugins.checkmk.models', 'CheckmkInventorizeAttributes'),
    'cmk_export_rules': ('application.plugins.checkmk.models', 'CheckmkRule'),
    'cmk_rules': ('application.plugins.checkmk.models', 'CheckmkRuleMngmt'),
    'cmk_groups': ('application.plugins.checkmk.models', 'CheckmkGroupRule'),
    'cmk_user': ('application.plugins.checkmk.models', 'CheckmkUserMngmt'),
    'cmk_rewrite': ('application.plugins.checkmk.models', 'CheckmkRewriteAttributeRule'),
    'cmk_sites': ('application.plugins.checkmk.models', 'CheckmkSite'),
    'cmk_site_settings': ('application.plugins.checkmk.models', 'CheckmkSettings'),
    'cmk_bi_aggregation': ('application.plugins.checkmk.models', 'CheckmkBiAggregation'),
    'cmk_bi_rule': ('application.plugins.checkmk.models', 'CheckmkBiRule'),
    'cmk_downtimes': ('application.plugins.checkmk.models', 'CheckmkDowntimeRule'),
    'cmk_dcd_rules': ('application.plugins.checkmk.models', 'CheckmkDCDRule'),
    'cmk_notification_rules': ('application.plugins.checkmk.models',
                              'CheckmkNotificationRule'),
    'cmk_folder_pool': ('application.plugins.checkmk.models', 'CheckmkFolderPool'),
    'cmk_site_pool': ('application.plugins.checkmk.models', 'CheckmkSitePool'),
    'cmk_passwords': ('application.plugins.checkmk.models', 'CheckmkPassword'),
    'host_objects': ('application.models.host', 'Host',
                     {'object_type__ne': 'template'}),
    'cmdb_templates': ('application.models.host', 'Host',
                       {'object_type': 'template'}),
    'projects': ('application.models.project', 'Project'),
    'saved_searches': ('application.models.saved_search', 'SavedSearch'),
    'system_config': ('application.models.config', 'Config'),
    'notification_channels': ('application.models.notification_channel',
                             'NotificationChannel'),
    'notification_rules': ('application.models.notification_rule',
                          'NotificationRule'),
    'accounts': ('application.models.account', 'Account'),
    'users': ('application.models.user', 'User'),
    'jira_export': ('application.plugins.jira_cloud.models', 'JiraExportRule'),
    'jira_filter': ('application.plugins.jira_cloud.models', 'JiraCloudFilterRule'),
    'jira_rewrite': ('application.plugins.jira_cloud.models',
                    'JiraCloudRewriteAttributeRule'),
    'idoit_rules': ('application.plugins.idoit.models', 'IdoitCustomAttributes'),
    'idoit_rewrite': ('application.plugins.idoit.models', 'IdoitRewriteAttributeRule'),
    'netbox_dcim_interfaces': ('application.plugins.netbox.models',
                                'NetboxDcimInterfaceAttributes'),
    'netbox_virtual_interfaces': ('application.plugins.netbox.models',
                                  'NetboxVirtualizationInterfaceAttributes'),
    'netbox_devices': ('application.plugins.netbox.models', 'NetboxCustomAttributes'),
    'netbox_ips': ('application.plugins.netbox.models', 'NetboxIpamIpaddressattributes'),
    'netbox_prefixes': ('application.plugins.netbox.models', 'NetboxIpamPrefixAttributes'),
    'netbox_vms': ('application.plugins.netbox.models', 'NetboxVirtualMachineAttributes'),
    'netbox_cluster': ('application.plugins.netbox.models', 'NetboxClusterAttributes'),
    'netbox_contacts': ('application.plugins.netbox.models', 'NetboxContactAttributes'),
    'netbox_dataflow_models': ('application.plugins.netbox.models', 'NetboxDataflowModels'),
    'netbox_dataflow_fields': ('application.plugins.netbox.models', 'NetboxDataflowAttributes'),
    'netbox_rewrites': ('application.plugins.netbox.models', 'NetboxRewriteAttributeRule'),
    'vmware_custom_attributes': ('application.plugins.vmware.models', 'VMwareCustomAttributes'),
    'vmware_rewrite_attributes': ('application.plugins.vmware.models', 'VMwareRewriteAttributes'),
    'syncer_rule_automation': ('application.plugins.rules.models', 'SyncerRuleAutomation'),
    'cron_groups': ('application.models.cron', 'CronGroup'),
}


rule_names = [(x, y[1]) for x, y in rules.items()]


# Collections that are deliberately NOT part of import/export: runtime
# state, caches, statistics and history. They are rebuilt by the syncer
# itself and would only bloat a configuration backup. Listing them here
# (instead of just leaving them out) is what lets the registry test fail
# whenever a new model shows up that nobody classified either way.
not_exported = {
    'AnsibleRunStats': 'Playbook run history',
    'CheckmkObjectCache': 'Rebuilt from the Checkmk API',
    'CheckmkRuleAnalysis': 'Result of the last rule analysis run',
    'CronStats': 'Cronjob run statistics',
    'FieldApproval': 'Approval queue, tied to live hosts',
    'HostInventoryTree': 'Inventory data of a single host',
    'HostLabelEvent': 'Label change history',
    'JiraSchemaCache': 'Rebuilt by jira sync_schema',
    'LogEntry': 'Syncer log',
    'NotificationState': 'Cooldown state of notification rules',
    'State': 'Open-changes counter',
}
