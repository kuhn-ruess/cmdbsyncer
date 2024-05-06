"""
Add Hosts into CMK Version 2 Installations
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member
#pylint: disable=logging-fstring-interpolation
import ast
import time
from application import app
from application.models.host import Host
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes as CC
from application import logger, log


class SyncCMK2(CMK2):
    """
    Sync Functions
    """
    log_details = []

    bulk_creates = []
    bulk_updates = []

    synced_hosts = []

    clusters = []
    cluster_updates = []

    checkmk_hosts = {}
    existing_folders = []
    existing_folders_attributes = {}
    custom_folder_attributes = {}

    label_prefix = False
    only_update_prefixed_labels = False

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
        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all folders from cmk")
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        api_folders = self.request(url, method="GET")
        if not api_folders[0]:
            raise CmkException("Cant connect or auth with CMK")
        for folder in api_folders[0]['value']:
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
                curren_folder, headers = self.request(url)
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
                _, headers = self.request(url, method="PUT",
                             data=payload,
                             additional_header=update_headers)
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
                _, headers = self.request(url, method="PUT",
                             data=payload,
                             additional_header=update_headers)
                etag = headers['etag']
            if update_attributes:
                payload = {
                    'update_attributes' : update_attributes
                }
                update_headers = {
                    'if-match': etag,
                }
                self.request(url, method="PUT",
                             data=payload,
                             additional_header=update_headers)
                print(f"{CC.OKGREEN} *{CC.ENDC} Update Attributes on Folder: {folder_name} "\
                      f"({update_attributes})")


    def fetch_checkmk_hosts(self):
        """
        Fetch all host currently in Checkmk
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all hosts from cmk")
        url = "domain-types/host_config/collections/all"
        api_hosts = self.request(url, method="GET")
        for host in api_hosts[0]['value']:
            self.checkmk_hosts[host['id']] = host


    def use_host(self, db_host):
        """
        Return if the Host is to be used
        for export or not
        """
        if self.limit:
            if db_host.hostname not in self.limit:
                return False
        if self.account_filter:
            filters = [x.strip() for x in self.account_filter.split(',')]
            if db_host.source_account_name not in filters:
                return False

        return True

    def handle_clusters(self):
        """ Create the Clusters """
        print(f"\n{CC.OKBLUE} -- {CC.ENDC}Check if we need to handle Clusters")
        for cluster in self.clusters:
            self.create_cluster(*cluster)
        for cluster in self.cluster_updates:
            self.update_cluster_nodes(*cluster)

    def cleanup_hosts(self):
        """ Cleanup Deleted hosts """

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        print(f"\n{CC.OKBLUE} -- {CC.ENDC}Check if we need to cleanup hosts")
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
                        url = f"/objects/host_config/{host}"
                        self.request(url, method="DELETE")
                        print(f"{CC.WARNING} *{CC.ENDC} Delete host {host}")


        if app.config['CMK_BULK_DELETE_HOSTS']:
            url = "/domain-types/host_config/actions/bulk-delete/invoke"
            chunks = list(self.chunks(delete_list, app.config['CMK_BULK_DELETE_OPERATIONS']))
            total = len(chunks)
            count = 1
            for chunk in chunks:
                print(f"{CC.OKGREEN} *{CC.ENDC} Send Bulk Request {count}/{total}")
                self.request(url, data={'entries': chunk }, method="POST")
                count += 1
        print(f"{CC.OKCYAN} *{CC.ENDC} Cleanup Done")

#   .-- Run Sync
    def run(self):
        """Run Job"""
        # In Order to delete Hosts from Checkmk, we collect the ones we sync

        start_time = time.time()

        self.fetch_checkmk_hosts()
        self.fetch_checkmk_folders()

        ## Start SYNC of Hosts into CMK
        print(f"\n{CC.OKCYAN} -- {CC.ENDC}Start Sync")
        db_objects = Host.get_export_hosts()
        total = db_objects.count()
        counter = 0
        for db_host in db_objects:
            counter += 1

            if not self.use_host(db_host):
                continue

            process = 100.0 * counter / total
            print(f"\n{CC.OKBLUE}({process:.0f}%){CC.ENDC} {db_host.hostname}")

            attributes = self.get_host_attributes(db_host, 'checkmk')
            if not attributes:
                print(f"{CC.WARNING} *{CC.ENDC} Host ignored by rules")
                continue
            next_actions = self.get_host_actions(db_host, attributes['all'])

            self.label_prefix = next_actions.get('label_prefix')

            label_prefix = ""
            if self.label_prefix:
                label_prefix = self.label_prefix
            labels = {f"{label_prefix}{k}":str(v) for k,v in attributes['filtered'].items()}

            self.only_update_prefixed_labels = next_actions.get('only_update_prefixed_labels')

            self.synced_hosts.append(db_host.hostname)
            labels['cmdb_syncer'] = self.account_id

            dont_move_host = next_actions.get('dont_move', False)
            dont_update_host = next_actions.get('dont_update', False)

            folder = '/'



            if 'move_folder' in next_actions:
                # Get the Folder where we move to
                # We need that even dont_move is set, because could be for the
                # inital creation
                folder = next_actions['move_folder']
                if '{' in next_actions.get('extra_folder_options', ''):
                    self.handle_extra_folder_options(next_actions['extra_folder_options'])

            cluster_nodes = [] # if true, we have a cluster
            if 'create_cluster' in next_actions:
                cluster_nodes = next_actions['create_cluster']

            if folder not in self.existing_folders:
                # We may need to create them later
                self.create_folder(folder)
                self.existing_folders.append(folder)

            additional_attributes = {}
            if 'parents' in next_actions:
                additional_attributes['parents'] = next_actions['parents']

            remove_attributes = []
            if 'remove_attributes' in next_actions:
                remove_attributes = next_actions['remove_attributes']
            logger.debug(f'Attributes will be removed: {remove_attributes}')

            for custom_attr in next_actions.get('custom_attributes', []):
                logger.debug(f"Check to add Custom Attribute: {custom_attr}")
                for attr_key in list(custom_attr):
                    if attr_key in remove_attributes:
                        del custom_attr[attr_key]
                        logger.debug(f"Don't add Attribute {attr_key}, its in remove_attributes")
                additional_attributes.update(custom_attr)

            for additional_attr in next_actions.get('attributes', []):
                logger.debug(f"Check to add Attribute: {additional_attr}")
                if attr_value := attributes['all'].get(additional_attr):
                    additional_attributes[additional_attr] = attr_value


            if db_host.hostname not in self.checkmk_hosts:
                # Create since missing
                if cluster_nodes:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Will be created as Cluster")
                    # We need to create them Later, since we not know that we have all nodes
                    self.clusters.append((db_host, folder, labels, \
                                        cluster_nodes, additional_attributes))
                else:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Need to created in Checkmk")
                    self.create_host(db_host, folder, labels, additional_attributes)
                # Add Host information to the dict, for later cleanup.
                # So no need to query all the hosta again
                self.checkmk_hosts[db_host.hostname] = \
                            {'extensions': {
                                'attributes':{
                                     'labels': {
                                          'cmdb_syncer': self.account_id
                                }}
                             }}
            elif not dont_update_host:
                cmk_host = self.checkmk_hosts[db_host.hostname]
                # Update if needed
                self.update_host(db_host, cmk_host, folder,
                                labels, additional_attributes, remove_attributes,
                                dont_move_host)
                if cluster_nodes:
                    cmk_cluster = cmk_host['extensions']['cluster_nodes']
                    self.cluster_updates.append((db_host, cmk_cluster, cluster_nodes))
            else:
                print(f"{CC.OKBLUE} *{CC.ENDC} Host is not to be updated")

            db_host.save()
        print()

        # Final Call to create missing hosts via bulk
        if self.bulk_creates:
            self.send_bulk_create_host(self.bulk_creates)
        if self.bulk_updates:
            self.send_bulk_update_host(self.bulk_updates)

        self.log_details.append(('info', f"Proccesed: {counter} of {total}"))
        if self.limit:
            log.log(f"Finished Sync to Checkmk Account: {self.account_name} because LIMIT",
                    source="checkmk_host_export", details=self.log_details)
            print(f"\n{CC.OKCYAN} -- {CC.ENDC}Stop processing in limit mode")
            return

        self.handle_clusters()
        self.cleanup_hosts()
        self.handle_folders()

        duration = time.time() - start_time
        log.log(f"Synced Hosts to Account: {self.account_name}", source="checkmk_host_export",
                details=self.log_details, duration=duration)

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
        if extra_opts := self.custom_folder_attributes.get(full_foldername):
            body.update(extra_opts)
        try:
            self.request(url, method="POST", data=body)
        except CmkException as error:
            # We have may an existing folder in 2.0 cmk
            logger.debug(f"Error creating Folder {error}")


    def create_folder(self, folder):
        """ Create given folder if not yet exsisting """
        folder_parts = folder.split('/')[1:]
        print(f"{CC.OKGREEN} *{CC.ENDC} Create Folder in Checkmk {folder}")
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

#.
#   .-- Create Host


    def send_bulk_create_host(self, entries):
        """
        Send Process to create hosts
        """
        print()
        print(f"{CC.OKGREEN} *{CC.ENDC} Send Bulk Create Request")
        url = "/domain-types/host_config/actions/bulk-create/invoke"
        try:
            self.request(url, method="POST", data={'entries': entries})
        except CmkException as error:
            self.log_details.append(('error', f"Bulk Create Error: {error}"))
            print(f"{CC.WARNING} *{CC.ENDC} CMK API ERROR {error}")

    def add_bulk_create_host(self, body):
        """
        Add a Host to bulk list, and Send
        """
        self.bulk_creates.append(body)
        if len(self.bulk_creates) >= int(app.config['CMK_BULK_CREATE_OPERATIONS']):
            try:
                self.send_bulk_create_host(self.bulk_creates)
            except CmkException as error:
                self.log_details.append(('error', f"Bulk Update Error: {error}"))
                print(f"{CC.WARNING} *{CC.ENDC} CMK API ERROR {error}")

            self.bulk_creates = []

    def create_host(self, db_host, folder, labels, additional_attributes=None):
        """
        Create the not yet existing host in CMK
        """
        body = {
            'host_name' : db_host.hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            }
        }
        if additional_attributes:
            # CMK BUG
            if app.config['CMK_22_23_HANDLE_TAG_LABEL_BUG']:
                self.log_details.append(('info', "CMK Tag bug workarround active"))
                print(f"{CC.WARNING} *{CC.ENDC} Removed TAGS because of CMK BUG")
                additional_attributes = {x:y for x,y in additional_attributes.items() \
                                            if not x.startswith('tag_')}

            body['attributes'].update(additional_attributes)
        if app.config['CMK_BULK_CREATE_HOSTS']:
            self.add_bulk_create_host(body)
            print(f"{CC.OKBLUE} *{CC.ENDC} Add to Bulk List")
        else:
            url = "/domain-types/host_config/collections/all"

            try:
                self.request(url, method="POST", data=body)
            except CmkException as error:
                self.log_details.append(('error', f"Host Create Error: {error}"))
                print(f"{CC.WARNING} *{CC.ENDC} CMK API ERROR {error}")
            print(f"{CC.OKGREEN} *{CC.ENDC} Created Host {db_host.hostname}")



#.
#   .-- Create Cluster
    def create_cluster(self, db_host, folder, labels, nodes, additional_attributes=None):
        """
        Create a not existing Cluster in CHeckmk
        """
        url = "/domain-types/host_config/collections/clusters"
        body = {
            'host_name' : db_host.hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            },
            'nodes' : nodes,
        }
        if additional_attributes:
            body['attributes'].update(additional_attributes)

        print(f"{CC.OKGREEN} *{CC.ENDC} Create Cluster {db_host.hostname}")
        self.request(url, method="POST", data=body)

#.
#   .-- Get Etag

    def get_etag(self, db_host, reason=""):
        """
        Return ETAG of host
        """
        print(f"{CC.OKGREEN} *{CC.ENDC} Read ETAG in CMK -> {reason}")
        url = f"objects/host_config/{db_host.hostname}"
        _, headers = self.request(url, "GET")
        return headers.get('ETag')

#.
#   .-- Update Cluster Nodes
    def update_cluster_nodes(self, db_host, cmk_nodes, syncer_nodes):
        """
        Update the Nodes of Cluster in case of change
        """
        if cmk_nodes != syncer_nodes:
            print(f"{CC.OKGREEN} *{CC.ENDC} Cluster has new Nodes {syncer_nodes}")
            etag = self.get_etag(db_host)
            update_headers = {
                'if-match': etag
            }
            update_url = f"/objects/host_config/{db_host.hostname}/properties/nodes"
            update_body = {
                'nodes': syncer_nodes
            }
            self.request(update_url, method="PUT",
                data=update_body,
                additional_header=update_headers)

#.
#   .-- Update Host
    def send_bulk_update_host(self, entries):
        """
        Send Update requests to CMK
        """

        print()
        print(f"{CC.OKGREEN} *{CC.ENDC} Send Bulk Update Request")
        url = "/domain-types/host_config/actions/bulk-update/invoke"
        try:
            self.request(url, method="PUT",
                         data={'entries': entries},
                        )
        except CmkException as error:
            self.log_details.append(('error', f"CMK API Error: {error}"))
            print(f"{CC.WARNING} *{CC.ENDC} CMK API ERROR {error}")

    def add_bulk_update_host(self, body):
        """
        Add a Host to bulk list, and Send
        """
        self.bulk_updates.append(body)
        if len(self.bulk_updates) >= int(app.config['CMK_BULK_UPDATE_OPERATIONS']):
            self.send_bulk_update_host(self.bulk_updates)
            self.bulk_updates = []

    def update_host(self, db_host, cmk_host, folder, \
                    labels, additional_attributes, remove_attributes, \
                    dont_move_host):
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

        logger.debug(f"Checkmk Body: {cmk_host}")

        etag = False
        # Check if we really need to move
        if not dont_move_host and current_folder != folder:
            print(f"{CC.OKGREEN} *{CC.ENDC} Host Moved from Folder: {current_folder} to {folder}")
            etag = self.get_etag(db_host, "Move Host")
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
            if new_etag := header.get('ETag'):
                etag = new_etag
            update_headers = {
                'if-match': etag,
            }
        if dont_move_host and current_folder != folder:
            print(f"{CC.WARNING} *{CC.ENDC} Folder Move to {folder} disabled. ")

        do_update = False
        do_update_labels = False
        do_update_attributes = False
        do_remove_attributes = False
        update_reasons = []
        cmk_attributes = cmk_host['extensions']['attributes']
        cmk_labels = cmk_attributes.get('labels', {})
        if self.only_update_prefixed_labels:
            # In this case, we secure all labels without the prefix
            for label, value in cmk_labels.items():
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
            update_url = f"objects/host_config/{db_host.hostname}"
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
                            etag = self.get_etag(db_host, "Update Host (1)")
                        update_headers = {
                            'if-match': etag,
                        }
                        try:
                            self.request(update_url, method="PUT",
                                         data=payload,
                                         additional_header=update_headers)
                            etag = False
                        except CmkException as error:
                            self.log_details.append(('error', f"CMK API Error: {error}"))
                            print(f"{CC.WARNING} *{CC.ENDC} CMK API ERROR {error}")
                        else:
                            print(f"{CC.OKGREEN} *{CC.ENDC} Updated Host in Checkmk")
                            print(f"   Reasons: {what}: {', '.join(update_reasons)}")
                    else:
                        payload['host_name'] = db_host.hostname
                        self.add_bulk_update_host(payload)
                        print(f"{CC.OKBLUE} *{CC.ENDC} Add to Bulk Update List for {what} update")
            db_host.set_export_sync()


#.
