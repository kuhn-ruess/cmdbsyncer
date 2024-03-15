# Hosttags

You can use the Syncer to manage given Host tags groups. 
This means, you can use the Attributes of your Hosts, to add and remove the predefined Tags.

Just keep in mind, that the Syncer can't remove Hostags which are still in use by rules.  In such cases, it will just no longer update the group, but not throw an exception. Just a silent error is shown.

This feature is also using Syncer Host-Based caching to speed up even the extraction of Data and rewrites from over 100,000 Hosts. The cache is auto-refreshed if the Host changes.

## How to configure
Go to:

_Rules → Checkmk → Checkmk Tags_

Create a new entry.

| Field | Description |
| :--------|:------------|
| Group Topic Name | The Category used for the Group in Checkmk |
| Group Title | The Human Readable Title of the Group, Example: My Locations|
| Group ID | The internal ID of the group. Example my_locations |
| Group Help | Help text for the User |
| Group Single Choice | creates a group with just one on-off choice |
| Group Multiply by List | Create a set of multiple Groups, based on a list. See docu below|
| Group Multiply List | Syncer Attribute containing a list, use get_list(), See doco below |
| Filter by Account | Should the Syncer create the Tags based on Attributes only from objects managed by given Account Name |
| Rewrite ID | Jinja rewrite for the internal ID of tag. Example: {{name\|lower()}} |
| Rewrite Title | Jinja rewrite the Human Readable Name of Tag Example: {{HOSTNAME\|capitalize()}}|
| Enabled | Enables the Rule |


Note: that {{ HOSTNAME }} is replaced by the Hostname. You can use every Host attribute here.
Also, the Rewrite Fields support custom [Syncer Functions](../advanced/jinja_functions.md).

Note 2: To the rewrite_id field, the cmk_cleanup_tag_id() function is applied automaticly. This is important to know, if you wan't to set tags. Make sure to use that Jinja Function.


## Group Multiply by List
If you use this mode, the Syncer will create multiple groups which can't be rewritten and are based fully on the outcome of a list.
In This case, you must use {{name}} as Placeholder for Topic Name and Title.
In Group Multiply by List, you need to provide a Python list. This is archived with the get_list helper.

Example:
```
{{get_list(YOUR_LIST_ATTRIBUTE)|safe}}
{{get_list(['Name1', 'Name2', "Name3'])|safe}}
```

Make sure to use |safe otherwise the System will escape that list

