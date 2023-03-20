"""
Cron Job Managment Helper
"""
from application import cron_register


def register_cronjob(job_name, job_function):
    """
    Register Cronjob to the System

    Pass the Unqiue Name and the Function reference.
    """
    cron_register[job_name] = job_function
