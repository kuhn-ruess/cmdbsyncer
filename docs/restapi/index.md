# Rest API Import

The Syncer can be used to import Data from all types of JSON Rest APIs. The Only requirement is that you know the Url, there is a Basic or Digest Auth and the list of Hosts to import are inside an array key.

First go to:
__Config → Accounts__
and create an Account of Type: "Remote Rest API".
When you click "Save and Continue Editing", you will see new fields in the Custom Fields Section.

For Address, set the Full URL to the API
User and Password set as next.  For Auth Type is basic and digest supported.

Next set "data_key", that's where the Hosts to be found. Example:

```
{ 
	"result": [
		{
			"id": "33",
			"label": "switch-xy",
			"ip": "10.10.11.12",
			"mask": "255.255.255.0",
			"status": "1",
		}
	]
}
```

The hostname_field in the example would be 'label'. Adapt it, accordantly to the response you get from your API. 

## Query the Data
The Query of Data can then be set in the Configuration for the Cronjob.
For testing on the Command line:

__./cmdbsyncer rest import_hosts YOURACCOUNT__

