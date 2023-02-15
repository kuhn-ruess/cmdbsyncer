# Update CMDB Syncer

As of now, if you want to Update the CMDB Syncer, just pull it from git agin

```
cd /var/www/cmdbsyncer
git pull
```

If using docker, now rebuild your image and restart.

If you have the UWSGI based installation, just reload uwsgi.

```
service uwsgi reload
```


## Problems
Sometimes the Application will not start up. In these cases, check the UWSGI Logs in /var/log.
It depends on which files your Distribution will log.

It's likely, then that a Module has changed. You can update the Modules easily:

```
cd /var/www/cmdbsyncer
source ENV/bin/activate
pip install -r requirements.txt
```

If you use Docker, you should not run n any problems. 

