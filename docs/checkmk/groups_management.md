# Groups Management

The Group Management Feature let you create contact-, Host- and Service-Groups based on Attributes you get from your Hosts.

The Syncer has a local Cache for all groups he created. That can be found in Rules → Checkmk → Object Cache. This is needed in order that the Syncer know which groups he can safely remove from Checkmk. So groups you created yourself are not touched. 
If you would delete the Cache Entry, the Syncer only takes over the groups with the next sync, if they are provided from your source again.

Also note, Checkmk has the Limitation that you can't have groups with the same name, even if it's another type. So, you can't have Contact Groups with the same name as Hostgroups. Use the Rewrite feature when needed.



## Rule Parameters
The Rule to configure everything you find in:

**Rules → Checkmk → CMK Groups Management**<br>

::: application.modules.checkmk.models.CmkGroupOutcome
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false

::: application.plugins.checkmk_configuration.export_groups
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false
