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


## Overwrite Options


### String Match
Simply add the new String as the new attribute or value
### Split
Add a pattern to the field. This Pattern contains a seperator where you want to split the string,
and then the index for the result.

Example:
```
/:0
```

Split example 127.0.0.1/24:
The String would split at /, result would ['127.0.0.1', '24']
From there it would pick the first (0) index, new value would be: 127.0.0.1


### Regex
Enter a Pattern with an Match Group

### Jinja
Full Power of Jinja2, you can use every Attribute of the host in {{ Brackets }} and manipulate using all Jinja Magic if you wan't. To access the hostname, use {{HOSTNAME}}

## Create a New Attribute
If you specify a not existing attribute as "old_attribute_name", it will be created as a new Attribute. Of course,, all Overwrite Options can be used for the value, so you could create a new
attribute which contains the value of multiple other attributes.


