"""
Add Hosts into CMK Version 2 Installations
"""
# pylint: disable=too-many-lines
import ast
import math
import multiprocessing
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application import app, logger, log
from application.models.host import Host
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes as CC


# pylint: disable=too-many-instance-attributes,too-many-public-methods
class SyncCMK2(CMK2):
    """
    Synchronization class for CheckMK version 2.x installations.

    This class handles the complete synchronization process between CMDB Syncer
    and CheckMK monitoring systems. It manages host creation, updates, deletion,
    cluster management, folder operations, and attribute synchronization with
    support for bulk operations and multiprocessing.

    Attributes:
        bulk_creates (list): Queue for bulk host creation operations
        bulk_updates (list): Queue for bulk host update operations
        disabled_hosts (list): List of hosts that are disabled/ignored
        synced_hosts (list): List of successfully synchronized hosts
        clusters (list): Queue for cluster creation operations
        cluster_updates (list): Queue for cluster update operations
        label_prefix (str|bool): Prefix for host labels, False if not used
        only_update_prefixed_labels (bool): Whether to only update prefixed labels
        dont_update_prefixed_labels (bool): Whether to avoid updating prefixed labels
        num_created (int): Counter for created hosts
        num_updated (int): Counter for updated hosts
        num_deleted (int): Counter for deleted hosts
        console (callable): Console output function for progress reporting
        limit (bool): Whether sync is running in limited mode

    Inherits from:
        CMK2: Base class providing CheckMK API functionality
    """

    bulk_creates = []
    bulk_updates = []

    disabled_hosts = []

    synced_hosts = []

    clusters = []
    cluster_updates = []


    label_prefix = False
    only_update_prefixed_labels = False
    dont_update_prefixed_labels = False

    num_created = 0
    num_updated  = 0
    num_deleted  = 0

    console = print

    limit = False

    @staticmethod
    def chunks(lst, n):
        """
        Split a list into smaller chunks of specified size.

        Args:
            lst (list): List to be chunked
            n (int): Size of each chunk

        Yields:
            list: Successive n-sized chunks from the input list
        """
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

#   .-- Get Host Actions
    def get_host_actions(self, db_host, attributes, persist_cache=True):
        """
        Get CheckMK-specific actions for a database host.

        Processes the host and its attributes through configured action rules
        to determine what operations need to be performed in CheckMK.

        Args:
            db_host (Host): Database host object
            attributes (dict): Host attributes dictionary

        Returns:
            dict: Dictionary of actions to be performed for this host
        """
        return self.actions.get_outcomes(
            db_host,
            attributes,
            persist_cache=persist_cache,
        )

#.

    def handle_extra_folder_options(self, full_path):
        """
        Parse and handle extra folder configuration options from path strings.

        Processes folder paths that contain embedded configuration options
        (separated by |) and adds them to the custom folder attributes.

        Args:
            full_path (str): Folder path potentially containing extra options
                           Format: "folder|{option1: value1, option2: value2}"
        """
        config_path = ""
        for current_path in full_path.split('/'):
            splitted = current_path.split('|')
            folder = splitted[0]
            if folder:
                config_path += "/" + folder
                if len(splitted) == 2:
                    if config_path not in self.custom_folder_attributes:
                        # Admin-editable move_folder / create_folder values —
                        # a malformed suffix would otherwise abort the host
                        # export for every host that touches this rule.
                        try:
                            parsed = ast.literal_eval(splitted[1])
                        except (ValueError, SyntaxError) as exc:
                            logger.error(
                                "Skipping malformed folder option at %r: %r (%s)",
                                config_path, splitted[1], exc,
                            )
                            log.log(
                                "Skipping malformed folder option",
                                details=[
                                    ('path', config_path),
                                    ('value', splitted[1]),
                                    ('error', str(exc)),
                                ],
                                source="Checkmk Export",
                            )
                            continue
                        self.custom_folder_attributes[config_path] = parsed


    # pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
    def handle_folders(self):
        """
        Update CheckMK folders with custom attributes and titles.

        Processes all folders that need attribute updates or title changes,
        making the necessary API calls to synchronize folder configuration
        with CheckMK.
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
            curren_folder = {}
            etag = None
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
                curren_folder.get('title') != update_attributes['title']:
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




    def fetch_checkmk_hosts(self):
        """
        Retrieve all hosts currently configured in CheckMK.

        Uses either folder-based or global host fetching depending on
        configuration settings to populate the checkmk_hosts dictionary.
        """
        extra_params = "?effective_attributes=false"
        if not self.checkmk_version.startswith('2.2'):
            extra_params += "&include_links=false"
        if app.config['CMK_GET_HOST_BY_FOLDER']:
            self._fetch_checkmk_host_by_folder(extra_params=extra_params)
        else:
            self.fetch_all_checkmk_hosts(extra_params=extra_params)


    def use_host(self, hostname, source_account_name):
        """
        Determine if a host should be included in the synchronization process.

        Applies configured filters including hostname limits and account filters
        to decide whether a host should be processed during sync.

        Args:
            hostname (str): Name of the host to check
            source_account_name (str): Source account name for the host

        Returns:
            bool: True if host should be synchronized, False otherwise
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
            allowed_filters = [f for f in filters if not f.startswith('!')]
            denied_filters = [f[1:] for f in filters if f.startswith('!')]

            if denied_filters and source_account_name in denied_filters:
                return False

            if allowed_filters and source_account_name not in allowed_filters:
                return False

        return True

    def handle_clusters(self):
        """
        Process cluster creation and node updates.

        Creates new clusters that were queued during host processing and
        updates existing clusters with new node configurations.
        """
        print(f"{CC.OKBLUE} -- {CC.ENDC}Check if we need to handle Clusters")
        for cluster in self.clusters:
            self.create_cluster(*cluster)
        for cluster in self.cluster_updates:
            self.update_cluster_nodes(*cluster)

    # pylint: disable-next=too-many-branches
    def cleanup_hosts(self):
        """
        Remove hosts from CheckMK that are no longer in the source system.

        Identifies hosts with the cmdb_syncer label that weren't part of this
        sync run and deletes them from CheckMK, either individually or in bulk.
        Respects deletion limits and configuration settings.
        """

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        print(f"{CC.OKBLUE} -- {CC.ENDC}Check if we need to cleanup hosts")
        if app.config['CMK_DONT_DELETE_HOSTS']:
            print(f"{CC.WARNING} *{CC.ENDC} Deletion of Hosts is disabled by setting")
            return
        delete_list = []
        synced_hosts = set(self.synced_hosts)
        for host, host_data in self.checkmk_hosts.items():
            host_labels = host_data['extensions']['attributes'].get('labels',{})
            if host_labels.get('cmdb_syncer') == self.account_id:
                if host not in synced_hosts:
                    # Delete host
                    delete_list.append(host)
                    print(f"{CC.WARNING} *{CC.ENDC} Going to Delete host {host}")

        if delete_limit := self.config.get('dont_delete_hosts_if_more_then'):
            if len(delete_list) > int(delete_limit):
                print(f"{CC.WARNING} *{CC.ENDC} Not deleting {len(delete_list)} hosts, "\
                      f"because limit is set to {delete_limit}")
                self.log_details.append(('error', f"Not deleting {len(delete_list)} hosts, "\
                                        f"because limit is set to {delete_limit}"))
                return

        if app.config['CMK_BULK_DELETE_HOSTS']:
            url = "/domain-types/host_config/actions/bulk-delete/invoke"
            chunk_size = app.config['CMK_BULK_DELETE_OPERATIONS']
            total = math.ceil(len(delete_list) / chunk_size) if delete_list else 0
            for count, chunk in enumerate(self.chunks(delete_list, chunk_size), start=1):
                self.num_deleted += len(chunk)
                print(f" * Send Bulk Request {count}/{total}")
                try:
                    self.request(url, data={'entries': chunk }, method="POST")
                except CmkException as exp:
                    self.log_details.append(("error", f"Host Bulk deletion failed: {exp}"))
                    print(f"{CC.WARNING} *{CC.ENDC} Bulk Host deletion failed failed {exp}")
                else:
                    pass
                self.num_deleted += len(chunk)
        else:
            for host in delete_list:
                url = f"/objects/host_config/{host}"
                try:
                    self.request(url, method="DELETE")
                    self.num_deleted += 1
                except CmkException as exp:
                    self.log_details.append(("error", f"Host deletion failed: {exp}"))
                    print(f"{CC.WARNING} *{CC.ENDC} Delete host {host} failed {exp}")
                else:
                    print(f"{CC.WARNING} *{CC.ENDC} Delete host {host}")


    def handle_host(self, db_host, host_actions, disabled_hosts):
        """
        Process a single host for synchronization (multiprocessing worker).

        Calculates host attributes and actions for a database host, adding
        results to shared dictionaries for later processing. This method
        is designed to run in separate processes.

        Args:
            db_host (Host): Database host object to process
            host_actions (dict): Shared dictionary for storing host actions
            disabled_hosts (list): Shared list for disabled/ignored hosts

        Returns:
            bool: True if host was processed successfully, False if ignored
        """
        attributes = self.get_attributes(db_host, 'checkmk')
        if not attributes:
            disabled_hosts.append(db_host.hostname)
            return False
        next_actions = self.get_host_actions(db_host, attributes['all'])
        host_actions[db_host.hostname] = (next_actions, attributes)
        return True

    def calculate_host_actions(self, db_host):
        """
        Calculate all sync data for one host and return it to the parent process.

        Returning plain data avoids the multiprocessing Manager overhead from
        shared dict/list proxies during large sync runs.
        """
        attributes = self.get_attributes(db_host, 'checkmk', persist_cache=False)
        if not attributes:
            if getattr(db_host, '_cache_dirty', False):
                db_host.save()
                setattr(db_host, '_cache_dirty', False)
            return db_host.hostname, False, None
        next_actions = self.get_host_actions(
            db_host,
            attributes['all'],
            persist_cache=False,
        )
        if getattr(db_host, '_cache_dirty', False):
            db_host.save()
            setattr(db_host, '_cache_dirty', False)
        return db_host.hostname, True, (next_actions, attributes)


    def handle_cmk_folder(self, next_actions):
        """
        Determine and create the target folder for a host.

        Processes folder-related actions including folder creation and movement,
        ensuring the target folder exists in CheckMK before host operations.

        Args:
            next_actions (dict): Dictionary of actions for the current host

        Returns:
            str: Target folder path for the host
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
        Process host attributes and determine which to add or remove.

        Combines custom attributes, inherited attributes, and removal rules
        to create the final attribute set for CheckMK host configuration.

        Args:
            next_actions (dict): Dictionary of actions for the current host
            attributes (dict): Host attributes from the database

        Returns:
            tuple: (additional_attributes, remove_attributes) dictionaries
        """
        additional_attributes = {}
        if 'parents' in next_actions:
            additional_attributes['parents'] = next_actions['parents']

        remove_attributes = []
        if 'remove_attributes' in next_actions:
            remove_attributes = next_actions['remove_attributes']

        logger.debug('Attributes will be removed: %s', remove_attributes)


        for custom_attr, custom_value in next_actions.get('custom_attributes', {}).items():
            logger.debug("Check to add Custom Attribute: %s", custom_attr)

            if custom_attr in remove_attributes:
                logger.debug("Don't add Attribute %s, its in remove_attributes", custom_attr)
                continue

            additional_attributes[custom_attr] = custom_value

        for additional_attr in next_actions.get('attributes', []):
            logger.debug("Check to add Attribute: %s", additional_attr)
            if attr_value := attributes['all'].get(additional_attr):
                additional_attributes[additional_attr] = attr_value

        if 'remove_if_attributes' in next_actions:
            for remove_if in next_actions['remove_if_attributes']:
                if remove_if not in additional_attributes:
                    remove_attributes.append(remove_if)

        return additional_attributes, remove_attributes


    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def create_or_update_host(self, hostname, folder, labels,
                                    cluster_nodes, additional_attributes,
                                    remove_attributes, dont_move_host,
                                    dont_update_host, dont_create_host):
        """
        Create new hosts or update existing ones in CheckMK.

        Central method that handles both host creation and updates based on
        current state. Manages clusters, regular hosts, and conversion between
        host types when necessary.

        Args:
            hostname (str): Name of the host
            folder (str): Target folder path
            labels (dict): Host labels dictionary
            cluster_nodes (list): List of cluster nodes (empty for regular hosts)
            additional_attributes (dict): Attributes to add/update
            remove_attributes (list): Attributes to remove
            dont_move_host (bool): Whether to skip folder movement
            dont_update_host (bool): Whether to skip host updates
            dont_create_host (bool): Whether to skip host creation
        """
        is_cluster = False
        if cluster_nodes:
            is_cluster = True
        if hostname in self.checkmk_hosts:
            self.set_status_attribute(hostname, True)
            if not dont_update_host:
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


            return

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
            self.set_status_attribute(hostname, True)
            # Add Host information to the dict, for later cleanup.
            # So no need to query all the hosta again
            self.checkmk_hosts[hostname] = \
                        {'extensions': {
                            'attributes':{
                                    'labels': {
                                        'cmdb_syncer': self.account_id
                            }}
                            }}
            return

        self.console(" * Host is not to be updated")

        self.set_status_attribute(hostname, False)
        print(f"DO NOT {hostname}")



    # pylint: disable-next=too-many-locals
    def calculate_attributes_and_rules(self):
        """
        Calculate host attributes and rules using multiprocessing.

        Processes all database hosts in parallel to determine their attributes
        and required actions. Uses multiprocessing for performance with large
        host inventories.

        Returns:
            dict: Dictionary mapping hostnames to (actions, attributes) tuples
        """
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()

        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating Hostrules and Attributes", total=total)
            host_actions = {}
            disabled_hosts = []
            with multiprocessing.Pool() as pool:
                tasks = []
                for db_host in db_objects:
                    if not self.use_host(db_host.hostname, db_host.source_account_name):
                        progress.advance(task1)
                        continue
                    task = pool.apply_async(self.calculate_host_actions, args=(db_host,))
                    tasks.append(task)

                progress.console.print("Waiting for Calculation to finish")
                for task in tasks:
                    try:
                        hostname, enabled, data = task.get(timeout=app.config['PROCESS_TIMEOUT'])
                    except multiprocessing.TimeoutError:
                        progress.console.print("- ERROR: Timeout for a object")
                    except Exception as error:  # pylint: disable=broad-exception-caught
                        if self.debug:
                            raise
                        progress.console.print(f"- ERROR: Timeout error for object ({error})")
                    else:
                        progress.advance(task1)
                        if enabled:
                            host_actions[hostname] = data
                        else:
                            disabled_hosts.append(hostname)
                pool.close()
                pool.join()


                if self.config.get('list_disabled_hosts'):
                    task2 = progress.add_task("List Disabled Hosts", total=len(disabled_hosts))
                    self.disabled_hosts = disabled_hosts
                    for host in disabled_hosts:
                        progress.advance(task2)
                        progress.console.print(f"- Disabled-> {host} disabled")
        return host_actions

    def set_status_attribute(self, hostname, is_existing=True):
        """
        Set inventory attribute for hosts that already exist in CheckMK.
        
        Args:
            hostname (str): Name of the host to set inventory for
            is_existing (bool): Status of object in Checkmk
        """
        if not app.config['CMK_WRITE_STATUS_BACK']:
            return
        try:
            db_host = Host.get_host(hostname, create=False)
            if db_host:
                # Set inventory attribute indicating this host exists in CheckMK
                inventory_data = {
                    'is_existing': is_existing,
                }
                db_host.update_inventory('checkmk_status', inventory_data)
                db_host.save()
        except Exception as exp:  # pylint: disable=broad-exception-caught
            self.log_details.append(('error', f"Failed to set inventory for {hostname}: {exp}"))
            print(f"{CC.WARNING} *{CC.ENDC} Failed to set inventory for {hostname}: {exp}")


#   .-- Run Sync
    # pylint: disable-next=too-many-locals,too-many-statements
    def run(self):
        """
        Execute the complete synchronization process.

        Main entry point that orchestrates the entire sync workflow:
        1. Fetch current CheckMK state (folders and hosts)
        2. Calculate attributes and actions for all hosts
        3. Process host creation/updates
        4. Handle clusters and folder operations
        5. Clean up deleted hosts
        6. Log synchronization statistics
        """
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
                labels = {f"{label_prefix}{k}":str(v).replace(':','-') \
                        for k,v in attributes['filtered'].items()}
                labels.update({x:y for x,y in attributes['all'].items()
                               if x.startswith('cmdbsyncer/')})
                if app.config['CMK_LOWERCASE_LABEL_VALUES']:
                    labels = {k:v.lower() for k, v in labels.items()}

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
        """
        Create a single folder in CheckMK via API.

        Helper method to create individual folders with proper title and
        attributes handling.

        Args:
            parent (str): Parent folder path
            subfolder (str): Name of the subfolder to create
        """
        url = "domain-types/folder_config/collections/all"
        if not subfolder:
            return
        title = subfolder

        mid_char = ""
        if parent != '/':
            mid_char = '/'
        full_foldername = f'{parent}{mid_char}{subfolder}'

        extra_opts = self.custom_folder_attributes.get(full_foldername, {})
        if 'title' in extra_opts:
            title = extra_opts['title']
            del extra_opts['title']
        body = {
            "name": subfolder,
            "title": title,
            "parent": parent,
        }
        if extra_opts:
            body.update({'attributes': extra_opts})
        try:
            self.request(url, method="POST", data=body)
            self.existing_folders.append(full_foldername)
        except CmkException as error:
            logger.debug("Error creating Folder %s", error)
            self.log_details.append(('error', f"Folder create problem {error}"))


    def create_folder(self, folder):
        """
        Create a complete folder hierarchy in CheckMK.

        Recursively creates all necessary parent folders to ensure the
        complete path exists in CheckMK.

        Args:
            folder (str): Complete folder path to create
        """
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
        Send bulk host creation requests to CheckMK API.

        Processes queued host creation operations in batches to improve
        performance with large numbers of hosts.

        Args:
            entries (list): List of host creation payloads
        """
        chunk_size = app.config['CMK_BULK_CREATE_OPERATIONS']
        total = math.ceil(len(entries) / chunk_size) if entries else 0
        for count, chunk in enumerate(self.chunks(entries, chunk_size), start=1):
            self.console(f" * Send Bulk Create Request {count}/{total}")
            url = "/domain-types/host_config/actions/bulk-create/invoke"
            try:
                self.request(url, method="POST", data={'entries': chunk})
                self.num_created += len(chunk)
            except CmkException as error:
                self.log_details.append((f'error_bulk_{count}', f"Bulk Create Error: {error}"))
                affected = str([x['host_name'] for x in chunk])
                self.log_details.append((f'error_affected_{count}', affected))
                self.console(f" * CMK API ERROR {error}")

    def add_bulk_create_host(self, body):
        """
        Add a host to the bulk creation queue.

        Queues host creation operations and triggers bulk processing when
        batch size limits are reached.

        Args:
            body (dict): Host creation payload
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
        Create a single host in CheckMK.

        Creates a regular (non-cluster) host either individually or by
        adding to the bulk creation queue.

        Args:
            hostname (str): Name of the host to create
            folder (str): Target folder path
            labels (dict): Host labels dictionary
            additional_attributes (dict, optional): Extra host attributes
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
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def create_cluster(self, hostname, folder, labels, nodes, additional_attributes=None):
        """
        Create a cluster host in CheckMK.

        Creates a cluster configuration with specified nodes and attributes.

        Args:
            hostname (str): Name of the cluster
            folder (str): Target folder path
            labels (dict): Cluster labels dictionary
            nodes (list): List of cluster node hostnames
            additional_attributes (dict, optional): Extra cluster attributes
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

    def get_etag(self, hostname, reason=""):  # pylint: disable=unused-argument
        """
        Retrieve ETag for a host (currently returns wildcard).

        Originally intended to fetch ETags for optimistic locking, but
        currently returns '*' due to CheckMK API issues.

        Args:
            hostname (str): Name of the host
            reason (str, optional): Reason for ETag retrieval (for logging)

        Returns:
            str: ETag value (currently always '*')
        """
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
        Update cluster node configuration when changes are detected.

        Compares current cluster nodes with desired configuration and
        updates CheckMK when differences are found.

        Args:
            hostname (str): Name of the cluster
            cmk_nodes (list): Current nodes in CheckMK
            syncer_nodes (list): Desired nodes from syncer
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
        Send bulk host update requests to CheckMK API.

        Processes queued host update operations in batches for improved
        performance with large numbers of updates.

        Args:
            entries (list): List of host update payloads
        """
        chunk_size = app.config['CMK_BULK_UPDATE_OPERATIONS']
        total = math.ceil(len(entries) / chunk_size) if entries else 0
        for count, chunk in enumerate(self.chunks(entries, chunk_size), start=1):
            self.console(f" * Send Bulk Update Request {count}/{total}")
            url = "/domain-types/host_config/actions/bulk-update/invoke"
            try:
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
        Add a host to the bulk update queue.

        Queues host update operations and triggers bulk processing when
        batch size limits are reached.

        Args:
            body (dict): Host update payload
        """
        self.bulk_updates.append(body)
        if not app.config['CMK_COLLECT_BULK_OPERATIONS'] and \
                len(self.bulk_updates) >= int(app.config['CMK_BULK_UPDATE_OPERATIONS']):
            self.send_bulk_update_host(self.bulk_updates)
            self.bulk_updates = []

    @staticmethod
    def _normalize_cmk_folder(current_folder):
        """Normalize a folder path returned by CheckMK (leading /, no trailing /)."""
        if not current_folder.startswith('/'):
            current_folder = "/" + current_folder
        # 2022-08-03 Problem with CMK:
        # Sometimes we have the / at the end, sometimes not. This should solve this
        if current_folder.endswith('/') and current_folder != '/':
            current_folder = current_folder[:-1]
        return current_folder

    def _move_host_if_needed(self, hostname, current_folder, folder, dont_move_host):
        """
        Move host to target folder if current and target differ.

        Returns:
            tuple(etag, ok): etag to reuse for subsequent requests (False if none),
                             ok=False if the move failed and the caller should abort.
        """
        check_folder = folder
        if self.checkmk_version.startswith('2.2') and folder.endswith('/'):
            check_folder = folder[:-1]

        if dont_move_host:
            if current_folder != folder:
                self.console(f" * Folder Move to {folder} disabled. ")
            return False, True

        if current_folder == check_folder:
            return False, True

        etag = self.get_etag(hostname, "Move Host")
        update_headers = {'if-match': etag}
        update_url = f"/objects/host_config/{hostname}/actions/move/invoke"
        update_body = {'target_folder': folder.replace('/', '~')}
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
            return False, False
        self.console(f" * Host Moved from Folder: {current_folder} to {folder}")
        return header.get('ETag', etag), True

    def _secure_existing_labels(self, labels, cmk_labels):
        """Preserve CMK-side labels according to dont_/only_update_prefixed_labels."""
        if self.dont_update_prefixed_labels:
            for label, value in cmk_labels.items():
                for chk_label in self.dont_update_prefixed_labels:
                    if label.startswith(chk_label):
                        labels[label] = value

        if self.only_update_prefixed_labels:
            for label, value in cmk_labels.items():
                if (label != 'cmdb_syncer'
                        and not label.startswith(self.only_update_prefixed_labels)
                        and label not in labels):
                    labels[label] = value

    # pylint: disable-next=too-many-locals
    def _build_host_update_body(self, cmk_host, labels,
                                additional_attributes, remove_attributes):
        """
        Decide what to update for this host and assemble the update body.

        Mutates `labels` (to preserve existing CMK labels) and `remove_attributes`
        (drops attributes that are not present in CheckMK to avoid API errors).

        Returns:
            tuple(update_body, update_reasons): update_body is {} if no update needed.
        """
        update_reasons = []
        cmk_attributes = cmk_host['extensions']['attributes']
        cmk_labels = cmk_attributes.get('labels', {})

        self._secure_existing_labels(labels, cmk_labels)

        do_update_labels = labels != cmk_labels
        if do_update_labels:
            update_reasons.append("Labels not match")

        do_update_attributes = False
        for key, value in additional_attributes.items():
            attr = cmk_attributes.get(key)
            if attr != value:
                update_reasons.append(
                    f"Update Extra Attribute: {key} Currently: {attr} != {value}")
                do_update_attributes = True
                break

        do_remove_attributes = False
        not_existing = []
        for attr in remove_attributes:
            if attr in cmk_attributes:
                update_reasons.append(f"Remove Extra Attribute: {attr}")
                do_remove_attributes = True
            else:
                not_existing.append(attr)
        # If we would try to remove an attribute not existing in checkmk,
        # the API would respond with an exception
        for attr in not_existing:
            remove_attributes.remove(attr)

        if not (do_update_labels or do_update_attributes or do_remove_attributes):
            return {}, update_reasons

        update_body = {'update_attributes': {}, 'tags': {}}
        if do_update_labels:
            update_body['labels'] = labels
        if do_update_attributes and additional_attributes:
            update_body['update_attributes'].update(
                {x: y for x, y in additional_attributes.items()
                 if not x.startswith('tag_')})
            update_body['tags'] = {x: y for x, y in additional_attributes.items()
                                   if x.startswith('tag_')}
        if do_remove_attributes and remove_attributes:
            update_body['remove_attributes'] = remove_attributes

        return update_body, update_reasons

    @staticmethod
    def _build_update_payload(what, update_body):
        """Build the per-field payload for a CheckMK update request.

        Returns None if there is nothing to send for this field.
        """
        if what == 'tags':
            if not update_body['tags']:
                return None
            return {"update_attributes": update_body['tags']}
        if what == 'labels':
            return {"update_attributes": {'labels': update_body[what]}}
        return {what: update_body[what]}

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _send_single_host_update(self, hostname, update_url, what,
                                 payload, update_reasons, etag):
        """Send a single per-field update for a host. Returns the (possibly reset) etag."""
        if not etag:
            etag = self.get_etag(hostname, "Update Host (1)")
        update_headers = {'if-match': etag}
        try:
            self.request(update_url, method="PUT",
                         data=payload, additional_header=update_headers)
            self.num_updated += 1
            etag = False
        except CmkException as error:
            self.log_details.append(('error', f"CMK API Error: {error}"))
            self.log_details.append(('affected_hosts', hostname))
            self.console(f" * CMK API ERROR {error}")
        else:
            self.console(" * Updated Host in Checkmk")
            self.console(f"   Reasons: {what}: {', '.join(update_reasons)}")
        return etag

    def _dispatch_host_update(self, hostname, update_body, update_reasons, etag):
        """
        Send the update to CheckMK, one field at a time.

        CheckMK currently fails if you send labels and tags at the same time,
        and you can't send update and remove attributes together either.
        """
        logger.debug("Syncer Update Body: %s", update_body)
        update_url = f"objects/host_config/{hostname}"

        for what in ('attributes', 'update_attributes',
                     'remove_attributes', 'labels', 'tags'):
            if what not in update_body:
                continue
            payload = self._build_update_payload(what, update_body)
            if payload is None:
                continue

            if app.config['CMK_BULK_UPDATE_HOSTS']:
                payload['host_name'] = hostname
                self.add_bulk_update_host(payload)
                self.console(f" * Add to Bulk Update List for {what} update")
                continue

            etag = self._send_single_host_update(
                hostname, update_url, what, payload, update_reasons, etag)

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def update_host(self, hostname, cmk_host, folder,
                    labels, additional_attributes, remove_attributes,
                    dont_move_host):
        """
        Update an existing host in CheckMK.

        Orchestrates folder moves, label/attribute updates, and attribute
        removals by delegating to dedicated helpers.

        Args:
            hostname (str): Name of the host to update
            cmk_host (dict): Current host data from CheckMK
            folder (str): Target folder path
            labels (dict): Updated labels dictionary
            additional_attributes (dict): Attributes to add/update
            remove_attributes (list): Attributes to remove
            dont_move_host (bool): Whether to skip folder movement
        """
        current_folder = self._normalize_cmk_folder(cmk_host['extensions']['folder'])
        logger.debug("Checkmk Body: %s", cmk_host)

        etag, ok = self._move_host_if_needed(
            hostname, current_folder, folder, dont_move_host)
        if not ok:
            return

        update_body, update_reasons = self._build_host_update_body(
            cmk_host, labels, additional_attributes, remove_attributes)

        if update_body:
            self._dispatch_host_update(hostname, update_body, update_reasons, etag)


#.
