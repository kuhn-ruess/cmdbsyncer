# Fileadmin

If you work, for example, with a lot of CSV Files in your Setup, but you don't want to access the Shell all the time, you can enable a simple Fileadmin Panel. This will appear in:
__Config → Files__ 

To enable it, just create a folder /srv/cmdbsyncer-files and make sure the Syncer can write in it.
This will Enable the Fileadmin. You can, of course, overwrite this Path by setting "FILEADMIN_PATH" in your [local config](lcl_config.md). This could be a good Idea if you're using Docker and you want to mount a Volume into the Container.





