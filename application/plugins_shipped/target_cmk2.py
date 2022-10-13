"""
Add Hosts into CMK Version 2 Installations
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get
from pprint import pprint
import click
from mongoengine.errors import DoesNotExist
from application.models.host import Host
from application.modules.cmk2 import CMK2, CmkException, cli_cmk
from application.helpers.get_account import get_account_by_name
from application.helpers.get_cmk_action import GetCmkAction
from application.helpers.get_label import GetLabel
from application.helpers.get_hostparams import GetHostParams
from application.helpers.debug import ColorCodes


#   .-- Class Update CMKv2
class UpdateCMKv2(CMK2):
    """
    Update Functions
    """


    def __init__(self, config):
        """
        Inital
        """
        super().__init__(config)
        self.account_id = str(config['_id'])
        self.action_helper = GetCmkAction()
        self.account_name = config['name']
        self.label_helper = GetLabel()
        self.params_helper = GetHostParams('export')

    def run(self): #pylint: disable=too-many-locals, too-many-branches
        """Run Job"""
        # In Order to delete Hosts from Checkmk, we collect the ones we sync
        synced_hosts = []

        # Get all current folders in order that we later now,
        # which we need to create
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}CACHE: Read all folders from cmk")
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        api_folders = self.request(url, method="GET")
        existing_folders = []
        for folder in api_folders[0]['value']:
            existing_folders.append(folder['extensions']['path'])



        # Get ALL hosts in order to compare them
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}CACHE: Read all hosts from cmk")
        url = "domain-types/host_config/collections/all"
        api_hosts = self.request(url, method="GET")
        cmk_hosts = {}
        for host in api_hosts[0]['value']:
            cmk_hosts[host['id']] = host



        ## Start SYNC of Hosts into CMK
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        db_objects = Host.objects(available=True)
        total = len(db_objects)
        counter = 0
        for db_host in db_objects:
            # Actions
            counter += 1
            process = 100.0 * counter / total
            print(f"\n{ColorCodes.HEADER}({process:.0f}%) {db_host.hostname}{ColorCodes.ENDC}")
            db_labels = db_host.get_labels()
            labels, extra_actions = self.label_helper.filter_labels(db_labels)

            host_params = self.params_helper.get_params(db_host.hostname)

            if host_params.get('ignore_host'):
                continue
            if host_params.get('custom_labels'):
                labels.update(host_params['custom_labels'])

            next_actions = self.action_helper.get_action(db_host, labels)
            if 'ignore' in next_actions or 'ignore_host' in next_actions:
                print(f"{ColorCodes.WARNING} *{ColorCodes.ENDC} Host ignored by rules")
                continue
            synced_hosts.append(db_host.hostname)
            labels['cmdb_syncer'] = self.account_id

            folder = '/'

            if 'move_folder' in next_actions:
                # Get the Folder where we move to
                folder = next_actions['move_folder']

            if folder not in existing_folders:
                # We may need to create them later
                self.create_folder(folder)
                existing_folders.append(folder)

            # Check if Host Exists

            additional_attributes = {}
            for action, value in extra_actions.items():
                if action.startswith('attribute_'):
                    attribute = action.split("_")[-1]
                    additional_attributes[attribute] = value

            if db_host.hostname not in cmk_hosts:
                # Create since missing
                print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Need to created in Checkmk")
                self.create_host(db_host, folder, labels, additional_attributes)
                # Add Host information to the dict, for later cleanup.
                # So no need to query all the hosta again
                cmk_hosts[db_host.hostname] = {'extensions': {
                                                    'attributes':{
                                                           'labels': {
                                                                'cmdb_syncer': self.account_id
                                                                }
                                                            }
                                                    }
                                                }
            else :
                cmk_host = cmk_hosts[db_host.hostname]
                # Update if needed
                self.update_host(db_host, cmk_host, folder,
                                labels, additional_attributes)



            db_host.save()

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Check if we need to cleanup hosts")
        for host, host_data in cmk_hosts.items():
            host_labels = host_data['extensions']['attributes'].get('labels',{})
            if host_labels.get('cmdb_syncer') == self.account_id:
                if host not in synced_hosts:
                    # Delete host
                    url = f"objects/host_config/{host}"
                    self.request(url, method="DELETE")
                    print(f"{ColorCodes.WARNING} *{ColorCodes.ENDC} Deleted host {host}")
        print(f"{ColorCodes.OKGREEN} *{ColorCodes.ENDC} Cleanup Done")

    def _create_folder(self, parent, subfolder):
        """ Helper to create tree of folders """
        url = "domain-types/folder_config/collections/all"
        if not subfolder:
            return
        body = {
            "name": subfolder,
            "title": subfolder,
            "parent": parent,
        }
        try:
            self.request(url, method="POST", data=body)
        except CmkException:
            # We ignore an existing folder
            pass


    def create_folder(self, folder):
        """ Create given folder if not yet exsisting """
        folder_parts = folder.split('/')[1:]
        if len(folder_parts) == 1:
            if folder_parts[0] == '':
                # we are in page root
                return
            parent = '/'
            subfolder = folder_parts[0]
            self._create_folder(parent, subfolder)
        else:
            next_parent = '/'
            for sub_folder in folder_parts:
                self._create_folder(next_parent, sub_folder)
                if next_parent == '/':
                    next_parent += sub_folder
                else:
                    next_parent  += '/' + sub_folder


    def create_host(self, db_host, folder, labels, additional_attributes=None):
        """
        Create the not yet existing host in CMK
        """
        url = "/domain-types/host_config/collections/all"
        body = {
            'host_name' : db_host.hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            }
        }
        if additional_attributes:
            body['attributes'].update(additional_attributes)

        self.request(url, method="POST", data=body)
        print(f"{ColorCodes.OKGREEN} *{ColorCodes.ENDC} Created Host {db_host.hostname}")


    def get_etag(self, db_host):
        """
        Return ETAG of host
        """
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Read ETAG in CMK")
        url = f"objects/host_config/{db_host.hostname}"
        _, headers = self.request(url, "GET")
        return headers['ETag']

    def update_host(self, db_host, cmk_host, folder, labels, additional_attributes=None):
        """
        Update a Existing Host in Checkmk
        """
        current_folder = cmk_host['extensions']['folder']
        # Hack slash in front, quick solution before redesign
        if not current_folder.startswith('/'):
            current_folder = "/" + current_folder

        # 2022-08-03 Problem with CMK:
        # Sometimes we have the / at the end,
        # sometimes not. This should solve this
        if current_folder.endswith('/') and current_folder != '/':
            current_folder = current_folder[:-1]

        etag = False
        # Check if we really need to move
        if current_folder != folder:
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Host Moved to Folder: {folder}")
            etag = self.get_etag(db_host)
            update_headers = {
                'if-match': etag
            }
            update_url = f"/objects/host_config/{db_host.hostname}/actions/move/invoke"
            update_body = {
                'target_folder': folder
            }
            _, header = self.request(update_url, method="POST",
                         data=update_body,
                         additional_header=update_headers)
            # Need to update the header after last request
            etag = header['Etag']
            update_headers = {
                'if-match': etag,
            }
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Moved Host from {current_folder}")


        # compare Labels
        cmk_labels = cmk_host['extensions']['attributes'].get('labels', {})

        if labels != cmk_labels:
            # We may already got the Etag by the folder move action
            if not etag:
                etag = self.get_etag(db_host)

            update_headers = {
                'if-match': etag,
            }
            update_url = f"objects/host_config/{db_host.hostname}"
            update_body = {
                'update_attributes': {
                    'labels' : labels,
                }
            }
            if additional_attributes:
                update_body['update_attributes'].update(additional_attributes)

            self.request(update_url, method="PUT",
                         data=update_body,
                         additional_header=update_headers)
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Updated Host in Checkmk")
            db_host.set_export_sync()

#.
#   .-- Command: Export Hosts
@cli_cmk.command('export_hosts')
@click.argument("account")
def cmk_host_export(account):
    """Add hosts to a CMK 2.x Insallation"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            job = UpdateCMKv2(target_config)
            job.run()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Command: Host Debug
@cli_cmk.command('debug_host')
@click.argument("hostname")
def debug_cmk_rules(hostname):
    """Show Rule Engine Outcome for given Host"""
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")
    action_helper = GetCmkAction(debug=True)
    label_helper = GetLabel()
    params_helper_export = GetHostParams('export')
    params_helper_import = GetHostParams('import')

    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        print("Host not found")
        return
    db_labels = db_host.get_labels()
    labels, extra_actions = label_helper.filter_labels(db_labels)
    params_export = params_helper_export.get_params(hostname)
    if params_export.get('custom_labels'):
        labels.update(params_export['custom_labels'])
    params_import = params_helper_import.get_params(hostname)
    actions = action_helper.get_action(db_host, labels)

    print()
    print(f"{ColorCodes.HEADER} ***** Final Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Labels in DB {ColorCodes.ENDC}")
    pprint(db_labels)
    print(f"{ColorCodes.UNDERLINE}Labels after Filter {ColorCodes.ENDC}")
    pprint(labels)
    print(f"{ColorCodes.UNDERLINE}Extra Actions for {db_host.hostname} {ColorCodes.ENDC}")
    print(extra_actions)
    print(f"{ColorCodes.UNDERLINE}Host Rule Parameters for Export {ColorCodes.ENDC}")
    pprint(params_export)
    print(f"{ColorCodes.UNDERLINE}Host Rule Parameters for Import {ColorCodes.ENDC}")
    pprint(params_import)
    print(f"{ColorCodes.UNDERLINE}Actions based on Action Rules {ColorCodes.ENDC}")
    pprint(actions)
#.
#   .-- Command: Print All
@cli_cmk.command('print_all')
def get_cmk_data():
    """Print List of all Hosts and their Labels"""
    action_helper = GetCmkAction()
    label_helper = GetLabel()

    for db_host in Host.objects():
        db_labels = db_host.get_labels()
        applied_labels, extra_actions = label_helper.filter_labels(db_labels)
        next_actions = action_helper.get_action(db_host, applied_labels)
        if not next_actions or 'ignore' in next_actions or 'ignore_host' in next_actions:
            continue
        print(f'Next Action: {next_actions}')
        print(f"Extra Actions for {db_host.hostname}")
        print(extra_actions)
        print(f"Labels for {db_host.hostname}")
        pprint(applied_labels)
#.
