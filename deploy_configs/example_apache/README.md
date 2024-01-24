This example config can be used with Apache and UWSGI. This is normaly the case if you install this API on a monitoring Server. Please make sure to also create the local_config.py in order to set the BASE_PREFIX to the URL you chosen in the Apache Settings. In the Example,, it would be /cmdbsyncer/.

Please note that in the uwsgi-config.py you find a plugin = python39.
This refers to python3.9. In newer Versions of Debian or Redhat you may have python3.10,
or python3.11, so you need to change that to plugin = python310 or python311
