# Groups Management

The Group Management Feature let you create contact-, Host- and Service-Groups based on Attributes you get from your Hosts.

Groups created by the Syncer, will always have and prefix containing the Syncer ID. This is need in order that Syncer also can remove his groups again, without touching groups you manually have created.  Also, we have to add hg, sg, cg as part of this prefix. This is due to a limitation in Checkmk. We cannot have e.g. a Contact Group with the same name of an e.g. Host group.

::: application.modules.checkmk.models.CmkGroupOutcome
    options:
      show_source: false