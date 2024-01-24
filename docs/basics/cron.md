# Cronjobs

The Syncer can handle the needed Cronjobs for your Automation.
You can choose all the Modules the Syncer Offers, and pass an Account which contains the config. Config would for example be a path of an CSV File.

To use the Feature, create a Cronjob Group:

## Cronjob Group
__Config → Cronjobs → Cronjob Group__

Each Group as an Interval and a Time range in which it should run.  With the Group, you set then the Jobs you want to run, and they will run in that order. If a Job Crashes, the hole Group will stop.  That is to, for example, not to delete hosts if the import failed.

## State Table
__Config → Cronjobs → State Table__

The State table keeps one Entry for all of your Groups. There you see the Time when the job runs next, or the last message and if there are errors.

If you want to reset jobs, just delete or edit these Entries.


## Run the Jobs
The Syncer does not have an integrated cron, so you need to call an Endpoint to enable everything. That can be done every 5 or 10 minutes. 
The Command you need to start is:


```
./cmdbsyncer cron run_jobs
```

And here is the Example including loading the local environment:

```
*/5 * * * * cd /var/www/cmdbsyncer && source /var/www/cmdbsyncer/ENV/bin/activate && ./cmdbsyncer cron run_jobs
```

Or all in Docker:

```
*/5 * * * * docker exec CONTAINER_ID /srv/cmdbsyncer cron run_jobs
```

