
"""
CSV Function
"""
#pylint: disable=too-many-arguments
import csv
import click
from application import app
from application.models.host import Host

@app.cli.group(name='csv')
def cli_csv():
    """CSV related commands"""



@cli_csv.command('compare_hosts')
@click.argument("csv_path")
@click.argument("delimiter", default=';')
@click.argument("hostname_field", default='host')
def compare_csv(csv_path, delimiter, hostname_field):
    """
    Check which Hosts in CSV are not in DB
    """
    #pylint: disable=no-member, consider-using-generator
    host_list = list([x.hostname for x in Host.objects()])
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            if hostname not in host_list:
                print(hostname)
