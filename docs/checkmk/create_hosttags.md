# Hosttags

You can use the Syncer to manage given Host tags groups. 
This means, you can use the Attributes of your Hosts, to add and remove the predefined Tags.

Just keep in mind, that the Syncer can't remove Hostags which are still in use by rules.  In such cases, it will just no longer update the group, but not throw an exception. Just a silent error is shown.

## How to configure
Go to:

_Rules → Checkmk → Checkmk Tags_

Create a new entry.

| Field | Description |
| :--------|:------------|
| Group Topic Name | The Category used for the Group in Checkmk |
| Group Title | The Human Readable Title of the Group, Example: My Locations|
| Group ID | The internal ID of the group. Example my_locations |
| Group Help | Helptext for the User |
| Filter by Account | Should the Syncer create the Tags based on Attributes only from objects managed by given Account Name |
| Rewrite ID | Jinja rewrite for the internal ID of tag. Example: {{name\|lower() }} |
| Rewrite Title | Jinja rewrite the Human Readable Name of Tag Exmpale: {{name\|capitalize()}}|
| Enabled | Enables the Rule |


Note: that {{ name }} is replaced by the Hostname
