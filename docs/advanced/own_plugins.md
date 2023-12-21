# Plugins
If you want to build a plugin to fetch any kind of data into the CMK Syncer, you learn here how to do that.

I recommend using the file plugins/example_source.py as base. Inside this file are comments who describe the functions needed to perform the import. Most Logic will be the part to query the data. The Cmdbsyner part is elementary. The full documentation of API Functions can be found [here](plugin_api.md)

## Steps for a simple Plugin
(Refer to the example_source.py to follow that list) 

1. Register a Command Argument, needed to call the Plugin
1. Register needed Parameters, normally just the Account name so that you can fetch e.g. the Credentials from the config.
1. Then actually Fetch the Account config
1. Build the Fetch Logic for your API, so that you have a List of Hosts and their Labels as Dictionary
1. Iterate your Hosts and get the reference based on the hostname
1. Set account to it to prevent overwrite from different source
1. Overwrite the Labels
1. Save the object
1. Add some Print Output if needed
1. Done :) 


Notes:
- Only Import syncer functions from syncerapi.v1, otherwise Updates can break your plugins