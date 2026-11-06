"""
Replay HTTP requests saved with --save-requests
"""
from ast import literal_eval
import requests
import click
from application import app

METHODS = {'get', 'post', 'put', 'delete', 'patch', 'head', 'options'}

@app.cli.group(name='request-runner')
def cli_requests():
    """Replay saved HTTP requests"""

def run_line(line):
    """
    Run the one request of a line: method||url||payload
    """
    method, url, data = line.split('||', 2)
    method = method.strip().lower()
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}")
    resp = requests.request(method, url, **literal_eval(data))
    print(f"({resp.status_code}) {url}")

def run_lines(lines, debug=False):
    """
    Run every line, a failing one doesn't stop the others.
    Returns the number of failed lines.
    """
    failed = 0
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            run_line(line)
        except (ValueError, SyntaxError, TypeError,
                requests.exceptions.RequestException) as error:
            if debug:
                raise
            failed += 1
            print(f"Line {number}: {type(error).__name__}: {error}")
    return failed

@cli_requests.command('run_request_file')
@click.argument("file_path")
@click.option("--debug", default=False, is_flag=True)
def run_requests(file_path, debug):
    """
    Run a File of requests
    """
    with open(file_path, newline='', encoding='utf-8') as requestfile:
        failed = run_lines(requestfile, debug)
    if failed:
        raise click.ClickException(f"{failed} line(s) failed")
