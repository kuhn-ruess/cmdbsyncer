"""
CronJobs
"""
#pylint: disable=too-many-arguments
import os
from datetime import datetime, timedelta
import click
from mongoengine.errors import DoesNotExist

from application import app, cron_register
from application.modules.debug import ColorCodes as CC
from application.models.cron import CronStats, CronGroup

@app.cli.group(name='cron')
def _cli_cron():
    """Cron Jobs"""

def get_stats(group):
    """
    Return Stats Object
    """
    try:
        return CronStats.objects.get(group=group)
    except DoesNotExist:
        new = CronStats()
        new.group = group
        new.next_run = datetime.now()
        return new


def next_run(interval):
    """
    Calculate next run of Job
    """
    now = datetime.now()
    minutes = False
    hours = False
    days = False
    # Stay Flexible for future intervals
    if interval == '10min':
        minutes = 10
    elif interval == 'hour':
        hours = 1
    elif interval == 'daily':
        days = 1

    if minutes:
        return now + timedelta(minutes=minutes)
    if days:
        return now + timedelta(days=days)
    if hours:
        return now + timedelta(hours=hours)
    return now

@_cli_cron.command('run_jobs')
@click.option("-v", default=False)
def run_jobs(v): #pylint: disable=invalid-name
    """
    Run all configured Jobs
    """
    now = datetime.now()
    for job in CronGroup.objects(enabled=True):
        stats = get_stats(job.name)

        # Add Time Delta of 1min to get jobs which never run before
        if not stats.is_running and stats.next_run <= now+timedelta(minutes=1):
            if v:
                print('-------------------------------------------------------------')
                print(f"{CC.HEADER} Running Group {job.name} {CC.ENDC}")
            stats.is_running = True
            stats.last_start = now
            stats.failure = False
            stats.save()
            for task in job.jobs:
                if v:
                    print(f"{CC.UNDERLINE}{CC.OKBLUE}Task: {task.name} {CC.ENDC}")
                stats.last_message = f"{now}: Started {task.name} (PID: {os.getpid()})"
                stats.save()
                try:
                    account_name = None
                    if task.account:
                        account_name = task.account.name
                    cron_register[task.command](account=account_name)
                except:
                    stats.is_running = False
                    stats.failure = True
                    stats.last_ended = None
                    stats.save()
                    # Don't Catch any exceptions. If for example the Import breaks,
                    # there should no export of deletion of hosts
                    raise

            stats.last_ended = datetime.now()
            stats.next_run = next_run(job.interval)
            stats.is_running = False
            stats.save()
