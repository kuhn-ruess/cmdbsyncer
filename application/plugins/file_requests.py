"""
Rule Import/ Export
"""
#pylint: disable=too-many-arguments
from application import app
from ast import literal_eval
import click

@app.cli.group(name='request-runner')
def cli_requests():
    """Request related commands"""

@cli_requests.command('run_request_file')
@click.argument("file_path")
@click.argument("account")
def run_requests(file_path, account):
    """
    Run a File of requests
    """
    with open(file_path, newline='', encoding='utf-8') as requestfile:
        for line in requestfile.readlines():
            if not line:
                continue
            method, url, data = line.split('||')
            data = literal_eval(data)
            print(method, url, data)
