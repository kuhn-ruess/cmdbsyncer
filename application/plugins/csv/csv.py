"""
CSV Function
"""
import csv
from application.models.host import Host
from application.modules.plugin import Plugin
from application.modules.debug import ColorCodes
from application.helpers.inventory import run_inventory


class CSV(Plugin):
    """Importer for CSV-backed host sources."""

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
            host_list = [x.hostname for x in Host.get_export_hosts()]
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            for row in reader:
                hostname = row[hostname_field]
                if hostname not in host_list:
                    print(hostname)

    # pylint: disable-next=too-many-locals
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
        self.name = f"CSV: Import Hosts ({filename})"
        self.log_details.append(('filename', filename))
        self.log_details.append(('path', csv_path))
        print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"
              f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
        num_rows = 0
        num_saved = 0
        num_errors = 0
        with open(csv_path, newline='', encoding=encoding) as csvfile:
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            for row in reader:
                num_rows += 1
                hostname = (row.get(hostname_field) or '').strip()
                try:
                    keys = list(row.keys())
                    for dkey in keys:
                        if not row[dkey]:
                            del row[dkey]
                    if self.config['rewrite_hostname']:
                        hostname = Host.rewrite_hostname(
                            hostname, self.config['rewrite_hostname'], row
                        )
                    host_obj = Host.get_host(hostname)
                    del row[hostname_field]
                    host_obj.update_host(row)
                    do_save = host_obj.set_account(
                        account_dict=self.config, import_id=import_id
                    )
                    if do_save:
                        host_obj.save()
                        num_saved += 1
                    print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} "
                          f"Update {hostname} Saved: {do_save}")
                except Exception as error:  # pylint: disable=broad-exception-caught
                    num_errors += 1
                    self.log_details.append(
                        (f'import_error {hostname or f"row {num_rows}"}', str(error))
                    )
                    print(f"Error: {error}")

        num_deleted = 0
        if extra_filter := self.config.get('delete_host_if_not_found_on_import'):
            num_deleted = Host.delete_host_not_found_on_import(
                self.config['name'], import_id, extra_filter
            ) or 0

        self.log_details.append(('num_rows', str(num_rows)))
        self.log_details.append(('num_saved', str(num_saved)))
        if num_errors:
            self.log_details.append(('num_errors', str(num_errors)))
        if extra_filter:
            self.log_details.append(('num_deleted', str(num_deleted)))

    def inventorize_hosts(self):
        """
        Inventorize data from a CSV
        """
        csv_path = self.config['path']
        encoding = self.config['encoding']
        delimiter = self.config['delimiter']
        hostname_field = self.config['hostname_field']

        filename = csv_path.split('/')[-1]
        self.name = f"CSV: Inventorize Hosts ({filename})"
        self.log_details.append(('filename', filename))
        self.log_details.append(('path', csv_path))
        print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"
              f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
        objects = []
        num_errors = 0
        rewrite = self.config.get('rewrite_hostname')
        with open(csv_path, newline='', encoding=encoding) as csvfile:
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            for row_idx, labels in enumerate(reader, start=1):
                hostname = (labels.get(hostname_field) or '').strip()
                if not hostname:
                    num_errors += 1
                    self.log_details.append(
                        (f'inventorize_error row {row_idx}',
                         f'missing hostname field {hostname_field!r}')
                    )
                    continue
                del labels[hostname_field]
                # Mirror the import path so inventory writes land on
                # the same host key as the matching importer.
                if rewrite:
                    hostname = Host.rewrite_hostname(hostname, rewrite, labels)
                objects.append((hostname, labels))

        self.log_details.append(('num_objects', str(len(objects))))
        if num_errors:
            self.log_details.append(('num_errors', str(num_errors)))

        run_inventory(self.config, objects)
