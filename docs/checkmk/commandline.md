# Commandline Options

The Checkmk System has the following Command Line Options.
You can access them with _./cmdbsyncer checkmk_

| Parameter | Description |
|:----------|:-------------|
| debug_host | Show all Matching Rules and Variable Outcomes |
| export_hosts | [Send Hosts to Given Checkmk Instance](export_rules.md) |
| export_groups | [Create Checkmk Groups (based on your rules)](groups_management.md)|
| export_rules | [Export your Checkmk rules to the Checkmk Instance](export_rules.md) |
| activate_changes | Activate Checkmk Changes on given Instance |
| bake_and_sign_agents | Bake the Agents in given Instance, You have to set bakery_key_id and bakery_passphrase as Custom Account Settings | 
| show_hosts | Just print out all Host which would be exported to Checkmk |
| inventorize_hosts | Run Inventory for attributes, used mainly for Ansible |



### Parameter Details
Here you find the Parameters for Modules not documented elsewhere.


::: application.plugins.checkmk.debug_host
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false

::: application.plugins.checkmk_configuration.inventorize_hosts
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false
  
::: application.plugins.checkmk_configuration.activate_changes
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false
  
::: application.plugins.checkmk_configuration.bake_and_sign_agents
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false


::: application.plugins.checkmk.show_hosts
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false
