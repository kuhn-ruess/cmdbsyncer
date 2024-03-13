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
| Filter by Account | Should the Syncer create the Tags based on Attributes only from objects managed by given Account Name |
| Rewrite ID | Jinja rewrite for the internal ID of tag. Example: {{name\|lower()}} |
| Rewrite Title | Jinja rewrite the Human Readable Name of Tag Example: {{HOSTNAME\|capitalize()}}|
| Enabled | Enables the Rule |


Note: that {{ HOSTNAME }} is replaced by the Hostname. You can use every Host attribute here.
Also, the Rewrite Fields support custom Syncer Functions.
So if you have, for example in your Attributes, a List of Dictionaries like this:

location = [{"site":""},{"section":""},{"level":""},{"room":""},{"description":""},{"note":""}]

Then you can use this Jinja Syntax to pick given values.

{{ merge_list_of_dicts(location)['room'] }}
