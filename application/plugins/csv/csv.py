"""
CSV Function
"""
#pylint: disable=too-many-arguments
import csv
from application.models.host import Host
from application.modules.plugin import Plugin
from application.modules.debug import ColorCodes
from application.helpers.get_account import get_account_by_name
from application.helpers.inventory import run_inventory


def compare_hosts(csv_path, delimiter, hostname_field, label_filter):
    """
    Compare lists from hosts which not in syncer
    """
    #pylint: disable=no-member, consider-using-generator
    if label_filter:
        host_list = []
        # we need to load the full plugins then
        plugin = Plugin()
        for host in Host.get_export_hosts():
            if label_filter in plugin.get_attributes(host, 'csv')['all']:
                host_list.append(host.hostname)
    else:
        host_list = list([x.hostname for x in Host.get_export_hosts()])
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            if hostname not in host_list:
                print(hostname)



def import_hosts(csv_path=None, delimiter=";", hostname_field="host", account=None):
    """
    Impor hosts from a CSV
    """
    #pylint: disable=no-member, consider-using-generator
    encoding = 'utf-8'
    if account:
        account = get_account_by_name(account)
        if 'hostname_field' in account:
            hostname_field = account['hostname_field']
        if 'delimiter' in account:
            delimiter = account['delimiter']
        if 'csv_path' in account:
            csv_path = account['csv_path']
        if 'path' in account:
            csv_path = account['path']
        if 'encoding' in account:
            encoding = account['encoding']

    if not csv_path:
        raise ValueError("No path given in account config")


    import_id = Plugin.get_unique_id()

    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    with open(csv_path, newline='', encoding=encoding) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            try:
                hostname = row[hostname_field].strip()
                keys = list(row.keys())
                for dkey in keys:
                    if not row[dkey]:
                        del row[dkey]
                if 'rewrite_hostname' in account and account['rewrite_hostname']:
                    hostname = Host.rewrite_hostname(hostname, account['rewrite_hostname'], row)
                print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
                host_obj = Host.get_host(hostname)
                del row[hostname_field]
                host_obj.update_host(row)
                if account:
                    do_save = host_obj.set_account(account_dict=account, import_id=import_id)
                else:
                    do_save = True
                    host_obj.set_account(f"csv_{filename}", filename, import_id=import_id)

                if do_save:
                    host_obj.save()
            except Exception as error:
                print(f"Error: {error}")


    if extra_filter := account.get('delete_host_if_not_found_on_import'):
        Host.delete_host_not_found_on_import(account['name'], import_id, extra_filter)


def inventorize_hosts(csv_path=None, delimiter=";", hostname_field="host", key="csv", account=None):
    """
    Inventorize data from a CSV
    """
    #pylint: disable=no-member, consider-using-generator
    encoding="utf-8"
    if account:

        account = get_account_by_name(account)

        if 'hostname_field' in account:
            hostname_field = account['hostname_field']
        if 'delimiter' in account:
            delimiter = account['delimiter']
        if 'csv_path' in account:
            csv_path = account['csv_path']
        if 'path' in account:
            csv_path = account['path']
        if 'inventorize_key' not in account:
            account['inventorize_key'] = key
        if 'encoding' in account:
            encoding = account['encoding']
    else:
        account = {
            'hostname_field': hostname_field,
            'delimiter': delimiter,
            'csv_path': csv_path,
            'inventorize_key': key,
        }


    if not csv_path:
        raise ValueError("No path given in account config")

    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    objects = []
    with open(csv_path, newline='', encoding=encoding) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for labels in reader:
            hostname = labels[hostname_field].strip()
            del labels[hostname_field]
            objects.append((hostname, labels))

    run_inventory(account, objects)