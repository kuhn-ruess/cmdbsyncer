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


class CSV(Plugin):

    def compare_hosts(self, csv_path, delimiter, hostname_field, label_filter):
        """
        Compare lists from hosts which not in syncer
        """
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
    
    
    
    def import_hosts(self):
        """
        Impor hosts from a CSV
        """
        import_id = self.get_unique_id()
        csv_path = self.config['path'] 
        encoding = self.config['encoding']
        delimiter = self.config['delimiter']
        hostname_field = self.config['hostname_field']

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
                    if self.config['rewrite_hostname']:
                        hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], row)
                    print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
                    host_obj = Host.get_host(hostname)
                    del row[hostname_field]
                    host_obj.update_host(row)
                    do_save = host_obj.set_account(account_dict=self.config, import_id=import_id)
                    if do_save:
                        host_obj.save()
                except Exception as error:
                    print(f"Error: {error}")
    
    
        if extra_filter := self.config.get('delete_host_if_not_found_on_import'):
            Host.delete_host_not_found_on_import(self.config['name'], import_id, extra_filter)
    
    
    def inventorize_hosts(self):
        """
        Inventorize data from a CSV
        """
        csv_path = self.config['path'] 
        encoding = self.config['encoding']
        delimiter = self.config['delimiter']
        hostname_field = self.config['hostname_field']
    
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

        run_inventory(self.config, objects)