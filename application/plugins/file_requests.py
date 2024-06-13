"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
from ast import literal_eval
import requests
import click
from application import app

@app.cli.group(name='request-runner')
def cli_requests():
    """Action Versioning System"""

def run(method, url, payload):
    """
    Run requests
    """
    jobs = {
        'get': requests.get(url, **payload),
        'post': requests.post(url, **payload),
        'put': requests.put(url, **payload),
        'delete': requests.delete(url, **payload),
    }
    resp = jobs[method]

    print(f"({resp.status_code}) {url}")

@cli_requests.command('run_request_file')
@click.argument("file_path")
def run_requests(file_path):
    """
    Run a File of requests
    """
    with open(file_path, newline='', encoding='utf-8') as requestfile:
        for line in requestfile.readlines():
            if not line:
                continue
            method, url, data = line.split('||')
            payload = literal_eval(data)
            run(method, url, payload)
