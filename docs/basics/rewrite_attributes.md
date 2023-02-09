# Rewrite Attributes

Different targets have different needs in how the name of an attribute have to be. Specially if you want to control Ansible our set custom Checkmk Attributes.

To cover that, you can rewrite Attributes for every Module. 

So for example if you import an attribute like the ipaddress from a CSV, there will be an prefix like csv_ipaddress. Use this rule to rename this csv_ipaddress back to ipaddress for example. 

## Possible Options:

::: application.modules.rule.models.AttributeRewriteAction
    options:
      show_source: false
      show_bases: false
      show_root_toc_entry: false

![](img/rewrite_action.png)


