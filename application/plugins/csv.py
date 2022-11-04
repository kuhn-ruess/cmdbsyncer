
"""
CSV Function
"""
#pylint: disable=too-many-arguments
import csv
import click
from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes

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
    host_list = list([x.hostname for x in Host.objects(available=True)])
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            if hostname not in host_list:
                print(hostname)

@cli_csv.command('import_hosts')
@click.argument("csv_path")
@click.argument("delimiter", default=';')
@click.argument("hostname_field", default='host')
def import_csv(csv_path, delimiter, hostname_field):
    """
    Import and Maintane Hosts from given CSV
    """
    #pylint: disable=no-member, consider-using-generator
    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)
            del row[hostname_field]
            host_obj.set_labels(row)
            host_obj.set_import_seen()
            host_obj.set_account(f"csv_{filename}", filename)
            host_obj.save()

@cli_csv.command('inventorize_hosts')
@click.argument("csv_path")
@click.argument("delimiter", default=';')
@click.argument("hostname_field", default='host')
@click.argument("key", default='csv')
def inventorize_csv(csv_path, delimiter, hostname_field, key):
    """
    Do inventory for fields in given csv
    """
    #pylint: disable=no-member, consider-using-generator
    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname, False)
            if host_obj:
                del row[hostname_field]
                host_obj.update_inventory(key, {f"{key}_{x}":y for x,y in row.items()})
                host_obj.save()
