"""
Add Hosts into CMK Version 2 Installations
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member
#pylint: disable=logging-fstring-interpolation, too-many-locals, too-many-positional-arguments
#pylint: disable=too-many-branches, too-many-instance-attributes, too-many-public-methods
#pylint: disable=too-many-lines
import ast
import multiprocessing
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application import app, logger, log
from application.models.host import Host
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes as CC


class SyncCMK2(CMK2):
    """
    Sync Functions
    """
    #log_details = []

    bulk_creates = []
    bulk_updates = []

    disabled_hosts = []

    synced_hosts = []

    clusters = []
    cluster_updates = []

    checkmk_hosts = {}
    existing_folders = []
    existing_folders_attributes = {}
    custom_folder_attributes = {}

    label_prefix = False
    only_update_prefixed_labels = False
    dont_update_prefixed_labels = False

    num_created = 0
    num_updated  = 0
    num_deleted  = 0

    console = None

    limit = False

    @staticmethod
    def chunks(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

#   .-- Get Host Actions
    def get_host_actions(self, db_host, attributes):
        """
        Get CMK Specific Actions
        """
        return self.actions.get_outcomes(db_host, attributes)

#.

    def handle_extra_folder_options(self, full_path):
        """
        We need to set extra Options to a Folder.
        So we try to find the paths of them and add them to the list
        """
        config_path = ""
        for current_path in full_path.split('/'):
            splitted = current_path.split('|')
            folder = splitted[0]
            if folder:
                config_path += "/" + folder
                if len(splitted) == 2:
                    if config_path not in self.custom_folder_attributes:
                        self.custom_folder_attributes[config_path] = ast.literal_eval(splitted[1])

    def fetch_checkmk_folders(self):
        """
        Fetch list of Folders in Checkmk
        """
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Fetching Current Folders", start=False)
            api_folders = self.request(url, method="GET")
            progress.update(task1, total=len(api_folders), start=True)
            if not api_folders[0]:
                raise CmkException("Cant connect or auth with CMK")
            for folder in api_folders[0]['value']:
                progress.update(task1, advance=1)
                path = folder['extensions']['path']
                attributes = folder['extensions']['attributes']
                self.existing_folders_attributes[path] = attributes
                self.existing_folders_attributes[path].update({'title': folder['title']})
                self.existing_folders.append(path)

    def handle_folders(self):
        """
        Check if Folders need Update
        """

        print(f"{CC.OKGREEN} -- {CC.ENDC}Check if we need to update Folders")
        for folder_name, target_attributes in self.custom_folder_attributes.items():
            add_attributes = {}
            update_attributes = {}
            for attr_name, attr_value in target_attributes.items():
                cmk_attributes = self.existing_folders_attributes.get(folder_name, {})
                if attr_name not in cmk_attributes:
                    add_attributes[attr_name] = attr_value
                else:
                    cmk_attr_value = cmk_attributes[attr_name]
                    if cmk_attr_value !=  attr_value:
                        update_attributes[attr_name] = attr_value
            folder_name_url = folder_name.replace('/', '~')
            url = f'/objects/folder_config/{folder_name_url}'
            if add_attributes or update_attributes:
                # get current E-Tag
                try:
                    curren_folder, headers = self.request(url)
                except CmkException as exp:
                    self.log_details.append(('error', f'GET Folder Exception: {exp}'))
                    continue
                if not curren_folder:
                    continue
                etag = headers['etag']
            if 'title' in update_attributes and \
                curren_folder['title'] != update_attributes['title']:
                new_title = update_attributes['title']
                print(f"{CC.OKGREEN} *{CC.ENDC} Update Title: {folder_name} to '{new_title}'")
                payload = {
                    'title' : new_title,
                }
                update_headers = {
                    'if-match': etag,
                }
                try:
                    _, headers = self.request(url, method="PUT",
                                 data=payload,
                                 additional_header=update_headers)
                except CmkException as exp:
                    self.log_details.append(('error', f'Create Folder Exception: {exp}'))
                    continue
                del update_attributes['title']
                etag = headers['etag']
            if add_attributes:
                print(f"{CC.OKGREEN} *{CC.ENDC} Add Attributes to Folder: "\
                      f"{folder_name} ({add_attributes})")
                payload = {
                    'attributes' : add_attributes
                }
                update_headers = {
                    'if-match': etag,
                }
                try:
                    _, headers = self.request(url, method="PUT",
                                 data=payload,
                                 additional_header=update_headers)
                except CmkException as exp:
                    self.log_details.append(('error', f'Create Folder Exception: {exp}'))
                    continue
                etag = headers['etag']
            if update_attributes:
                payload = {
                    'update_attributes' : update_attributes
                }
                update_headers = {
                    'if-match': etag,
                }
                try:
                    self.request(url, method="PUT",
                             data=payload,
                             additional_header=update_headers)
                except CmkException as exp:
                    self.log_details.append(('error', f'Update Folder Exception: {exp}'))
                    continue
                print(f"{CC.OKGREEN} *{CC.ENDC} Update Attributes on Folder: {folder_name} "\
                      f"({update_attributes})")


    def _fetch_all_checkmk_hosts(self):
        """
        Classic full Fetch
        """
        url = "domain-types/host_config/collections/all"
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Fetching Hosts", start=False)
            progress.console.print("Waiting for Checkmk Response")
            api_hosts = self.request(url, method="GET")
            progress.update(task1, total=len(api_hosts), start=True)
            for host in api_hosts[0]['value']:
                self.checkmk_hosts[host['id']] = host
                progress.update(task1, advance=1)



    def _get_hosts_of_folder(self, folder, return_dict):
        """ Get Hosts of given folder """
        folder = folder.replace('/','~')
        url = f"objects/folder_config/{folder}/collections/hosts"
        api_hosts = self.request(url, method="GET")
        for host in api_hosts[0]['value']:
            return_dict[host['id']] = host

    def _fetch_checkmk_host_by_folder(self):
        """
        Check the folder Structure and get hosts
        whit multiple request
        """
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            num_folders = len(self.existing_folders)

            task1 = progress.add_task("Fetching Hosts folder by folder", total=num_folders)
            manager = multiprocessing.Manager()
            return_dict = manager.dict()
            with multiprocessing.Pool() as pool:
                for folder in self.existing_folders:
                    pool.apply_async(self._get_hosts_of_folder,
                                     args=(folder, return_dict,),
                                     callback=lambda x: progress.advance(task1))

                pool.close()
                pool.join()
                self.checkmk_hosts.update(return_dict)


    def fetch_checkmk_hosts(self):
        """
        Fetch all host currently in Checkmk
        """
        if app.config['CMK_GET_HOST_BY_FOLDER']:
            self._fetch_checkmk_host_by_folder()
        else:
            self._fetch_all_checkmk_hosts()


    def use_host(self, hostname, source_account_name):
        """
        Return if the Host is to be used
        for export or not
        """
        if self.config.get('limit_by_hostnames'):
            self.limit = True
            if hostname not in [x.strip() for x in self.config['limit_by_hostnames'].split(',')]:
                return False

        # Remove with 4.0
        if self.config.get('account_filter'):
            raise ValueError("Please migrate 'account_filter' to "\
                            "'limit_by_accounts' in Accounts settings")

        if self.config.get('limit_by_accounts'):
            filters = [x.strip() for x in self.config['limit_by_accounts'].split(',')]
            if source_account_name not in filters:
                return False

        return True

    def handle_clusters(self):
        """ Create the Clusters """
        print(f"{CC.OKBLUE} -- {CC.ENDC}Check if we need to handle Clusters")
        for cluster in self.clusters:
            self.create_cluster(*cluster)
        for cluster in self.cluster_updates:
            self.update_cluster_nodes(*cluster)

    def cleanup_hosts(self):
        """ Cleanup Deleted hosts """

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        print(f"{CC.OKBLUE} -- {CC.ENDC}Check if we need to cleanup hosts")
        if app.config['CMK_DONT_DELETE_HOSTS']:
            print(f"{CC.WARNING} *{CC.ENDC} Deletion of Hosts is disabled by setting")
            return
        delete_list = []
        for host, host_data in self.checkmk_hosts.items():
            host_labels = host_data['extensions']['attributes'].get('labels',{})
            if host_labels.get('cmdb_syncer') == self.account_id:
                if host not in self.synced_hosts:
                    # Delete host

                    if app.config['CMK_BULK_DELETE_HOSTS']:
                        delete_list.append(host)
                        print(f"{CC.WARNING} *{CC.ENDC} Going to Delete host {host}")
                    else:
                        self.num_deleted += 1
                        url = f"/objects/host_config/{host}"
                        try:
                            self.request(url, method="DELETE")
                        except CmkException as exp:
                            self.log_details.append(("error", f"Host deletion failed: {exp}"))
                            print(f"{CC.WARNING} *{CC.ENDC} Delete host {host} failed {exp}")
                        else:
                            print(f"{CC.WARNING} *{CC.ENDC} Delete host {host}")


        if app.config['CMK_BULK_DELETE_HOSTS']:
            url = "/domain-types/host_config/actions/bulk-delete/invoke"
            chunks = list(self.chunks(delete_list, app.config['CMK_BULK_DELETE_OPERATIONS']))
            total = len(chunks)
            count = 1
            for chunk in chunks:
                self.num_deleted += len(chunk)
                print(f" * Send Bulk Request {count}/{total}")
                try:
                    self.request(url, data={'entries': chunk }, method="POST")
                except CmkException as exp:
                    self.log_details.append(("error", f"Host Bulk deletion failed: {exp}"))
                    print(f"{CC.WARNING} *{CC.ENDC} Bulk Host deletion failed failed {exp}")
                else:
                    count += 1
                self.num_deleted += len(chunk)


    def handle_host(self, db_host, host_actions, disabled_hosts):
        """
        All Calculation for a Host
        """
        attributes = self.get_host_attributes(db_host, 'checkmk')
        if not attributes:
            disabled_hosts.append(db_host.hostname)
            return False
        next_actions = self.get_host_actions(db_host, attributes['all'])
        host_actions[db_host.hostname] = (next_actions, attributes)
        return True


    def handle_cmk_folder(self, next_actions):
        """
        Get the Folder the Hosts needs to Go
        """
        folder = '/'

        if '{' in next_actions.get('extra_folder_options', ''):
            self.handle_extra_folder_options(next_actions['extra_folder_options'])
        if 'create_folder' in next_actions:
            if '{' in next_actions.get('create_folder_extra_folder_options', ''):
                self.handle_extra_folder_options(next_actions['create_folder_extra_folder_options'])
            create_folder = next_actions['create_folder']
            if create_folder not in self.existing_folders:
                # We may need to create them later
                self.create_folder(create_folder)
                self.existing_folders.append(create_folder)

        if 'move_folder' in next_actions:
            # Get the Folder where we move to
            # We need that even dont_move is set, because could be for the
            # inital creation
            folder = next_actions['move_folder']

            if folder not in self.existing_folders:
                # We may need to create them later
                self.create_folder(folder)
                self.existing_folders.append(folder)

        return folder


    def handle_attributes(self, next_actions, attributes):
        """
        Determine Hosts Checkmk Attributes
        """

        additional_attributes = {}
        if 'parents' in next_actions:
            additional_attributes['parents'] = next_actions['parents']

        remove_attributes = []
        if 'remove_attributes' in next_actions:
            remove_attributes = next_actions['remove_attributes']

        logger.debug(f'Attributes will be removed: {remove_attributes}')


        for custom_attr, custom_value in next_actions.get('custom_attributes', {}).items():
            logger.debug(f"Check to add Custom Attribute: {custom_attr}")

            if custom_attr in remove_attributes:
                logger.debug(f"Don't add Attribute {custom_attr}, its in remove_attributes")
                continue

            additional_attributes[custom_attr] = custom_value

        for additional_attr in next_actions.get('attributes', []):
            logger.debug(f"Check to add Attribute: {additional_attr}")
            if attr_value := attributes['all'].get(additional_attr):
                additional_attributes[additional_attr] = attr_value

        if 'remove_if_attributes' in next_actions:
            for remove_if in next_actions['remove_if_attributes']:
                if remove_if not in additional_attributes:
                    remove_attributes.append(remove_if)

        return additional_attributes, remove_attributes


    def create_or_update_host(self, hostname, folder, labels,
                                    cluster_nodes, additional_attributes,
                                    remove_attributes, dont_move_host,
                                    dont_update_host, dont_create_host):
        """
        Do creation or update actions
        """
        is_cluster = False
        if cluster_nodes:
            is_cluster = True
        if hostname not in self.checkmk_hosts:
            # If here so that it not goes into update mode
            if not dont_create_host:
                # Create since missing
                if is_cluster:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Will be created as Cluster")
                    # We need to create them Later, since we not know that we have all nodes
                    self.clusters.append((hostname, folder, labels, \
                                        cluster_nodes, additional_attributes))
                else:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Need to created in Checkmk")
                    self.create_host(hostname, folder, labels, additional_attributes)
                # Add Host information to the dict, for later cleanup.
                # So no need to query all the hosta again
                self.checkmk_hosts[hostname] = \
                            {'extensions': {
                                'attributes':{
                                     'labels': {
                                          'cmdb_syncer': self.account_id
                                }}
                             }}
        elif not dont_update_host:
            cmk_host = self.checkmk_hosts[hostname]

            if is_cluster and not cmk_host['extensions']['is_cluster']:
                url = f"/objects/host_config/{hostname}"
                try:
                    self.request(url, method="DELETE")
                except CmkException as exp:
                    self.log_details.append(("error", f"Host deletion failed: {exp}"))
                    print(f"{CC.WARNING} *{CC.ENDC} Host deletion failed failed {exp}")
                    return

                print(f"{CC.WARNING} *{CC.ENDC} Deleted host to create it as Cluster")
                # Make sure it's added again
                self.clusters.append((hostname, folder, labels, \
                                    cluster_nodes, additional_attributes))
                return


            # Update if needed
            self.update_host(hostname, cmk_host, folder,
                            labels, additional_attributes, remove_attributes,
                            dont_move_host)
            if is_cluster:
                cmk_cluster = cmk_host['extensions']['cluster_nodes']
                self.cluster_updates.append((hostname, cmk_cluster, cluster_nodes))
        else:
            self.console(" * Host is not to be updated")



    def calculate_attributes_and_rules(self):
        """
        Calculate Attributes and Rules
        """
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()

        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating Hostrules and Attributes", total=total)
            manager = multiprocessing.Manager()
            host_actions = manager.dict()
            disabled_hosts = manager.list()
            with multiprocessing.Pool() as pool:
                tasks = []
                for db_host in db_objects:
                    if not self.use_host(db_host.hostname, db_host.source_account_name):
                        progress.advance(task1)
                        continue
                    task = pool.apply_async(self.handle_host,
                                     args=(db_host, host_actions, disabled_hosts),
                                     callback=lambda x: progress.advance(task1))
                    tasks.append(task)
                    #@TODO
                    # .get() slows the process, console print is not up to date
                    # New concept will be needed for outputs
                    progress.console.print(f"- Started on {db_host.hostname}")
                    #result = x.get()
                    #if not result:
                    #    progress.console.print("--> !! Host Disabled")

                progress.console.print("Waiting for Calculation to finish")
                for task in tasks:
                    try:
                        task.get(timeout=5)
                    except multiprocessing.TimeoutError:
                        progress.console.print("- ERROR: Timout for a object")
                    except Exception:
                        progress.console.print(f"- ERROR: Timout error for object ({Exception})")
                pool.close()
                pool.join()


                if self.config.get('list_disabled_hosts'):
                    task2 = progress.add_task("List Disabled Hosts", total=total)
                    self.disabled_hosts = disabled_hosts
                    for host in disabled_hosts:
                        progress.advance(task2)
                        progress.console.print(f"- Disabled-> {host} disabled")
        return dict(host_actions)



#   .-- Run Sync
    def run(self):
        """Run Job"""
        # In Order to delete Hosts from Checkmk, we collect the ones we sync

        self.name=f"Sync Hosts to Account: {self.account_name}"
        self.source="checkmk_host_export"


        self.fetch_checkmk_folders()
        self.fetch_checkmk_hosts()

        ## Start SYNC of Hosts into CMK

        host_actions = self.calculate_attributes_and_rules()

        total = len(host_actions)
        print(f"\n{CC.OKCYAN} -- {CC.ENDC}Start Sync")
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Handling Checkmk Actions", total=total)
            self.console = progress.console.print
            for hostname, data in host_actions.items():
                export_details = []
                progress.console.print(f"* {hostname}")

                next_actions = data[0]
                attributes = data[1]
                self.label_prefix = next_actions.get('label_prefix')

                label_prefix = ""
                if self.label_prefix:
                    label_prefix = self.label_prefix
                labels = {f"{label_prefix}{k}":str(v) for k,v in attributes['filtered'].items()}

                self.only_update_prefixed_labels = next_actions.get('only_update_prefixed_labels')
                self.dont_update_prefixed_labels = next_actions.get('dont_update_prefixed_labels')


                self.synced_hosts.append(hostname)
                labels['cmdb_syncer'] = self.account_id

                dont_move_host = next_actions.get('dont_move', False)
                dont_update_host = next_actions.get('dont_update', False)
                dont_create_host = next_actions.get('dont_create', False)

                folder = self.handle_cmk_folder(next_actions)
                export_details.append(("folder", folder))


                cluster_nodes = [] # if true, we have a cluster
                if 'create_cluster' in next_actions:
                    cluster_nodes = next_actions['create_cluster']

                additional_attributes, remove_attributes = \
                        self.handle_attributes(next_actions, attributes)

                export_details += [
                  ('add_attributes', str(additional_attributes)),
                  ('remove_attributes', str(additional_attributes)),
                ]

                if app.config['CMK_DETAILED_LOG']:
                    log.log("", affected_hosts=hostname,
                        source="checkmk_host_export_details", details=export_details)


                self.create_or_update_host(hostname, folder, labels,
                                      cluster_nodes, additional_attributes,
                                      remove_attributes, dont_move_host,
                                      dont_update_host, dont_create_host)
                progress.advance(task1)


        # Final Call to create missing hosts via bulk
        if self.bulk_creates:
            self.send_bulk_create_host(self.bulk_creates)
        if self.bulk_updates:
            self.send_bulk_update_host(self.bulk_updates)

        if self.limit:
            log.log(f"Finished Sync to Checkmk Account: {self.account_name} because LIMIT",
                    source="checkmk_host_export", details=self.log_details)
            print(f"\n{CC.OKCYAN} -- {CC.ENDC}Stop processing in limit mode")
            return

        self.handle_clusters()
        self.cleanup_hosts()
        self.handle_folders()


        self.log_details.append(('num_total', str(total)))
        self.log_details.append(('num_created', str(self.num_created)))
        self.log_details.append(('num_updated', str(self.num_updated)))
        self.log_details.append(('num_deleted', str(self.num_deleted)))
        self.log_details.append(('disabled_hosts', str(self.disabled_hosts)))

#.
#   .-- Create Folder
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
        mid_char = ""
        if parent != '/':
            mid_char = '/'
        full_foldername = f'{parent}{mid_char}{subfolder}'
        self.existing_folders.append(full_foldername)
        if extra_opts := self.custom_folder_attributes.get(full_foldername):
            body.update({'attributes': extra_opts})
        try:
            self.request(url, method="POST", data=body)
        except CmkException as error:
            logger.debug(f"Error creating Folder {error}")
            self.log_details.append(('error', f"Folder create problem {error}"))


    def create_folder(self, folder):
        """ Create given folder if not yet exsisting """
        folder_parts = folder.split('/')[1:]
        self.console(f" * Create Folder in Checkmk {folder}")
        if len(folder_parts) == 1:
            if folder_parts[0] == '':
                # we are in page root
                return
            parent = '/'
            sub_folder = folder_parts[0]
            if sub_folder not in self.existing_folders:
                self._create_folder(parent, sub_folder)
        else:
            next_parent = '/'
            for sub_folder in folder_parts:
                extr = ""
                if not next_parent.endswith('/') and not sub_folder.startswith('/'):
                    extr = "/"
                next_subfolder = f'{next_parent}{extr}{sub_folder}'
                if next_subfolder  not in self.existing_folders:
                    self._create_folder(next_parent, sub_folder)
                if next_parent == '/':
                    next_parent += sub_folder
                else:
                    next_parent  += '/' + sub_folder

#.
#   .-- Create Host


    def send_bulk_create_host(self, entries):
        """
        Send Process to create hosts
        """
        chunks = list(self.chunks(entries, app.config['CMK_BULK_CREATE_OPERATIONS']))
        total = len(chunks)
        count = 1
        for chunk in chunks:
            self.console(f" * Send Bulk Create Request {count}/{total}")
            count += 1
            url = "/domain-types/host_config/actions/bulk-create/invoke"
            try:
                self.request(url, method="POST", data={'entries': chunk})
                self.num_created += len(chunk)
            except CmkException as error:
                self.log_details.append(('error', f"Bulk Create Error: {error}"))
                self.log_details.append(('error_affected', str([x['host_name'] for x in chunk])))
                self.console(f" * CMK API ERROR {error}")

    def add_bulk_create_host(self, body):
        """
        Add a Host to bulk list, and Send
        """
        self.bulk_creates.append(body)
        if not app.config['CMK_COLLECT_BULK_OPERATIONS'] and \
                len(self.bulk_creates) >= int(app.config['CMK_BULK_CREATE_OPERATIONS']):
            try:
                self.send_bulk_create_host(self.bulk_creates)
            except CmkException as error:
                self.log_details.append(('error', f"Bulk Update Error: {error}"))
                self.console(f" * CMK API ERROR {error}")

            self.bulk_creates = []

    def create_host(self, hostname, folder, labels, additional_attributes=None):
        """
        Create the not yet existing host in CMK
        """
        body = {
            'host_name' : hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            }
        }
        if additional_attributes:
            body['attributes'].update(additional_attributes)
        if app.config['CMK_BULK_CREATE_HOSTS']:
            self.add_bulk_create_host(body)
            self.console(" * Add to Bulk List")
        else:
            url = "/domain-types/host_config/collections/all"

            try:
                self.request(url, method="POST", data=body)
                self.num_created += 1
            except CmkException as error:
                self.log_details.append(('error', f"Host Create Error: {error}"))
                self.console(f" * CMK API ERROR {error}")
            self.console(f" * Created Host {hostname}")



#.
#   .-- Create Cluster
    def create_cluster(self, hostname, folder, labels, nodes, additional_attributes=None):
        """
        Create a not existing Cluster in CHeckmk
        """
        if not nodes:
            print(f"{CC.OKGREEN} *{CC.ENDC} Cluster {hostname} not created -> No Nodes")
            return
        url = "/domain-types/host_config/collections/clusters"
        body = {
            'host_name' : hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            },
            'nodes' : nodes,
        }
        if additional_attributes:
            body['attributes'].update(additional_attributes)

        print(f"{CC.OKGREEN} *{CC.ENDC} Create Cluster {hostname}")
        try:
            self.request(url, method="POST", data=body)
        except CmkException as error:
            self.log_details.append(('error_cluster', f"Cluster Create Error: {error}"))

#.
#   .-- Get Etag

    def get_etag(self, hostname, reason=""):
        """
        Return ETAG of host
        """
        # pylint: disable=unused-argument
        # 2.2 and 2.3p6: This Call here is deleting the host...
        #self.console(f" * Read ETAG in CMK -> {reason}")
        #url = f"/objects/host_config/{hostname}?effective_attributes=false"
        #_, headers = self.request(url, "GET")
        #return headers.get('ETag')
        return '*'

#.
#   .-- Update Cluster Nodes
    def update_cluster_nodes(self, hostname, cmk_nodes, syncer_nodes):
        """
        Update the Nodes of Cluster in case of change
        """
        if sorted(cmk_nodes) != sorted(syncer_nodes):
            print(f"{CC.OKGREEN} *{CC.ENDC} Cluster has new Nodes {syncer_nodes} vs {cmk_nodes}")
            etag = self.get_etag(hostname)
            update_headers = {
                'if-match': etag
            }
            update_url = f"/objects/host_config/{hostname}/properties/nodes"
            update_body = {
                'nodes': syncer_nodes
            }
            try:
                self.request(update_url, method="PUT",
                    data=update_body,
                    additional_header=update_headers)
            except CmkException as error:
                self.log_details.append(('error_cluster', f"Cluster Node Update Errror: {error}"))

#.
#   .-- Update Host
    def send_bulk_update_host(self, entries):
        """
        Send Update requests to CMK
        """
        chunks = list(self.chunks(entries, app.config['CMK_BULK_UPDATE_OPERATIONS']))
        total = len(chunks)
        count = 1
        for chunk in chunks:
            self.console(f" * Send Bulk Update Request {count}/{total}")
            url = "/domain-types/host_config/actions/bulk-update/invoke"
            try:
                count += 1
                self.request(url, method="PUT",
                             data={'entries': chunk},
                            )
                self.num_updated += len(chunk)
            except CmkException as error:
                self.log_details.append(('error', f"CMK API Error: {error}"))
                self.log_details.append(('error_affected', str([x['host_name'] for x in chunk])))
                self.console(f" * CMK API ERROR {error}")

    def add_bulk_update_host(self, body):
        """
        Add a Host to bulk list, and Send
        """
        self.bulk_updates.append(body)
        if not app.config['CMK_COLLECT_BULK_OPERATIONS'] and \
                len(self.bulk_updates) >= int(app.config['CMK_BULK_UPDATE_OPERATIONS']):
            self.send_bulk_update_host(self.bulk_updates)
            self.bulk_updates = []

    def update_host(self, hostname, cmk_host, folder, \
                    labels, additional_attributes, remove_attributes, \
                    dont_move_host):
        """
        Update an Existing Host in Checkmk
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

        logger.debug(f"Checkmk Body: {cmk_host}")


        etag = False
        # Check if we really need to move
        check_folder = folder
        if app.config['CMK_SUPPORT'] == '2.2' and folder.endswith('/'):
            check_folder = folder[:-1]
        if not dont_move_host and current_folder != check_folder:
            etag = self.get_etag(hostname, "Move Host")
            update_headers = {
                'if-match': etag
            }
            update_url = f"/objects/host_config/{hostname}/actions/move/invoke"
            update_body = {
                'target_folder': folder.replace('/','~')
            }
            header = {}
            try:
                _, header = self.request(update_url, method="POST",
                             data=update_body,
                             additional_header=update_headers)
            except CmkException as exp:
                self.log_details.append(('error', f'Move exception: {hostname} {exp}'))
            if 'error' in header:
                self.console(f" * Host Move Problem: {header['error']}")
                self.log_details.append(('error', f"Move Error: {hostname} {header['error']}"))
                return
            self.console(f" * Host Moved from Folder: {current_folder} to {folder}")

            # Need to update the header after last request
            if new_etag := header.get('ETag'):
                etag = new_etag
            update_headers = {
                'if-match': etag,
            }

        if dont_move_host and current_folder != folder:
            self.console(f" * Folder Move to {folder} disabled. ")

        do_update = False
        do_update_labels = False
        do_update_attributes = False
        do_remove_attributes = False
        update_reasons = []
        cmk_attributes = cmk_host['extensions']['attributes']
        cmk_labels = cmk_attributes.get('labels', {})

        if self.dont_update_prefixed_labels:
            for label, value in cmk_labels.items():
                # in this case, we keep the original cmk label
                for chk_label in self.dont_update_prefixed_labels:
                    if label.startswith(chk_label):
                        labels[label] = value

        if self.only_update_prefixed_labels:
            for label, value in cmk_labels.items():
                # In this case, we secure all labels without the prefix
                if label != 'cmdb_syncer' \
                    and not label.startswith(self.only_update_prefixed_labels):
                    if label not in labels:
                        # Of course only update if not already there,
                        # otherwise we have maybe old data
                        labels[label] = value

        if labels != cmk_labels:
            do_update = True
            do_update_labels = True
            update_reasons.append("Labels not match")

        for key, value in additional_attributes.items():
            attr = cmk_attributes.get(key)
            if attr != value:
                update_reasons.append(f"Update Extra Attribute: {key} Currently: {attr} != {value}")
                do_update = True
                do_update_attributes = True
                break


        not_existing = []
        for attr in remove_attributes:
            if attr in cmk_attributes:
                update_reasons.append(f"Remove Extra Attribute: {attr}")
                do_update = True
                do_remove_attributes = True
            else:
                not_existing.append(attr)
        for attr in not_existing:
            # If we would try to remove
            # A attribute not exiting in checkmk,
            # The API would respond with an exception
            remove_attributes.remove(attr)


        if do_update:
            update_url = f"objects/host_config/{hostname}"
            update_body = {
                'update_attributes': {},
                'tags': {},
            }

            if do_update_labels:
                update_body['labels'] = labels
            if do_update_attributes and additional_attributes:
                update_body['update_attributes'].update({x:y for x,y in \
                                additional_attributes.items() if not x.startswith('tag_')})
                update_body['tags'] = {x:y for x,y in additional_attributes.items() \
                                                if x.startswith('tag_')}

            if do_remove_attributes and remove_attributes:
                update_body['remove_attributes'] = remove_attributes


            logger.debug(f"Syncer Update Body: {update_body}")


            # CHeckmk currently fails if you send labels and tags the same time
            # and you cant send update and remove attributes at the same time
            for what in ['attributes', 'update_attributes',
                         'remove_attributes', 'labels', 'tags']:
                if what in update_body:
                    if what == 'tags':
                        if not update_body['tags']:
                            continue
                        payload = {
                            "update_attributes": update_body['tags']
                        }
                    elif what == 'labels':
                        payload = {
                            "update_attributes": {'labels': update_body[what]},
                        }
                    else:
                        payload = {
                            what: update_body[what],
                        }

                    if not app.config['CMK_BULK_UPDATE_HOSTS']:
                        if not etag: # We may already have one
                            etag = self.get_etag(hostname, "Update Host (1)")
                        update_headers = {
                            'if-match': etag,
                        }
                        try:
                            self.request(update_url, method="PUT",
                                         data=payload,
                                         additional_header=update_headers)
                            self.num_updated += 1
                            etag = False
                        except CmkException as error:
                            self.log_details.append(('error', f"CMK API Error: {error}"))
                            self.log_details.append(('affected_hosts', hostname))
                            self.console(f" * CMK API ERROR {error}")
                        else:
                            self.console(" * Updated Host in Checkmk")
                            self.console(f"   Reasons: {what}: {', '.join(update_reasons)}")
                    else:
                        payload['host_name'] = hostname
                        self.add_bulk_update_host(payload)
                        self.console(f" * Add to Bulk Update List for {what} update")


#.
