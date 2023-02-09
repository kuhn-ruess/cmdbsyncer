# Set all Kinds of Attributes to Checkmk

If you'd like to, you can set a rule to convert Syncer Attributes into Checkmk Attributes, or even just create your Custom ones using Placeholders. Only the Name needs to match the required Checkmk Name. To make that sure for existing Attributes, you can rewrite them using a rule in CMK → Rewrite Attributes. 

The Easy way to find out this Attribute's Name, is to check with the Swagger Documentation provided in Checkmk

Let's do some Examples.
The Rule for everything is **Checkmk → CMK Export Rules**.

## Find out the Checkmk Attributes Name
If you don't know the name already, just set a Host manually with this attribute and query it using Swagger Documentation.
Here is an Example how to do that:

Open Swagger:
![](img/open_swagger.png)

Find and Test Endpoint:

![](img/api_host_endpoint.png)

## Setting an IP Address Attribute
To use an existing Syncer Attribute, which either already have the correct name ipaddress, or is rewritten to this name, use the "Create Checkmk-Attribute" Action like this:

![](img/outcome_create_attribute.png)

In the Checkmk API, it would look like this:
![](img/api_ipaddress.png)

## Setting Management Boards as Attributes
For this, you can create Custom Attributes. If for example all your physical hosts, have a DNS name for the Management Board which contains the actual Hostname, you can do it like this:

![](img/outcome_custom_attribute.png)
Here the Hostname could be srvlx100, the management Board rib-srvlx100.

In addition, please note the Second Outcome, since the Management Boards require at least to settings.

And here how to find this example in the CMK API:
![](img/api_managementboard.png)
