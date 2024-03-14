"""
Add Hosts into CMK Version 2 Installations
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member, too-many-locals, too-many-branches
#pylint: disable=logging-fstring-interpolation
from application import app
from application.models.host import Host
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes as CC
from application import logger


class SyncCMK2(CMK2):
    """
    Sync Functions
    """

    @staticmethod
    def chunks(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    bulk_creates = []
    bulk_updates = []


#   .-- Get Host Actions
    def get_host_actions(self, db_host, attributes):
        """
        Get CMK Specific Actions
        """
        return self.actions.get_outcomes(db_host, attributes)

#.
#   .-- Run Sync
    def run(self): #pylint: disable=too-many-locals, too-many-branches
        """Run Job"""
        # In Order to delete Hosts from Checkmk, we collect the ones we sync
        synced_hosts = []

        # Get all current folders in order that we later now,
        # which we need to create
        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all folders from cmk")
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        api_folders = self.request(url, method="GET")
        existing_folders = []
        if not api_folders[0]:
            raise CmkException("Cant connect or auth with CMK")
        for folder in api_folders[0]['value']:
            existing_folders.append(folder['extensions']['path'])



        # Get ALL hosts in order to compare them
        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all hosts from cmk")
        url = "domain-types/host_config/collections/all"
        api_hosts = self.request(url, method="GET")
        cmk_hosts = {}
        for host in api_hosts[0]['value']:
            cmk_hosts[host['id']] = host



        ## Start SYNC of Hosts into CMK
        print(f"\n{CC.OKCYAN} -- {CC.ENDC}Start Sync")
        db_objects = Host.get_export_hosts()
        total = len(db_objects)
        counter = 0
        clusters = []
        cluster_updates = []
        for db_host in db_objects:
            counter += 1
            if self.limit:
                if db_host.hostname not in self.limit:
                    continue
            if self.account_filter:
                filters = [x.strip() for x in self.account_filter.split(',')]
                if db_host.source_account_name not in filters:
                    continue

            # Actions
            process = 100.0 * counter / total
            print(f"\n{CC.HEADER}({process:.0f}%) {db_host.hostname}{CC.ENDC}")
            attributes = self.get_host_attributes(db_host, 'checkmk')


            if not attributes:
                print(f"{CC.WARNING} *{CC.ENDC} Host ignored by rules")
                continue
            next_actions = self.get_host_actions(db_host, attributes['all'])


            labels = {k:str(v) for k,v in attributes['filtered'].items()}

            synced_hosts.append(db_host.hostname)
            labels['cmdb_syncer'] = self.account_id

            dont_move_host = next_actions.get('dont_move', False)

            folder = '/'

            if 'move_folder' in next_actions:
                # Get the Folder where we move to
                # We need that even dont_move is set, because could be for the
                # inital creation
                folder = next_actions['move_folder']

            cluster_nodes = [] # if true, we have a cluster
            if 'create_cluster' in next_actions:
                cluster_nodes = next_actions['create_cluster']

            if folder not in existing_folders:
                # We may need to create them later
                self.create_folder(folder)
                existing_folders.append(folder)

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


            if db_host.hostname not in cmk_hosts:
                # Create since missing
                if cluster_nodes:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Will be created as Cluster")
                    # We need to create them Later, since we not know that we have all nodes
                    clusters.append((db_host, folder, labels, \
                                        cluster_nodes, additional_attributes))
                else:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Need to created in Checkmk")
                    self.create_host(db_host, folder, labels, additional_attributes)
                # Add Host information to the dict, for later cleanup.
                # So no need to query all the hosta again
                cmk_hosts[db_host.hostname] = \
                            {'extensions': {
                                'attributes':{
                                     'labels': {
                                          'cmdb_syncer': self.account_id
                                }}
                             }}
            else:
                cmk_host = cmk_hosts[db_host.hostname]
                # Update if needed
                self.update_host(db_host, cmk_host, folder,
                                labels, additional_attributes, remove_attributes,
                                dont_move_host)
                if cluster_nodes:
                    cmk_cluster = cmk_host['extensions']['cluster_nodes']
                    cluster_updates.append((db_host, cmk_cluster, cluster_nodes))



            db_host.save()

        # Final Call to create missing hosts via bulk

        chunks = list(self.chunks(self.bulk_creates, app.config['CMK_BULK_CREATE_OPERATIONS']))
        total = len(chunks)
        count = 1
        for chunk in chunks:
            print(f"{CC.OKGREEN} *{CC.ENDC} Send Bulk Create Requests {count}/{total}")
            self.send_create_host(chunk)
            count += 1

        if app.config['CMK_BULK_UPDATE_HOSTS']:
            chunks = list(self.chunks(self.bulk_updates, app.config['CMK_BULK_UPDATE_OPERATIONS']))
            total = len(chunks)
            count = 1
            for chunk in chunks:
                print(f"{CC.OKGREEN} *{CC.ENDC} Send Bulk Update Requests {count}/{total}")
                self.send_update_host(chunk)
                count += 1

        if self.limit:
            print(f"\n{CC.OKCYAN} -- {CC.ENDC}Stop processing in limit mode")
            return
        ## Create the Clusters
        print(f"\n{CC.OKBLUE} -- {CC.ENDC}Check if we need to handle Clusters")
        for cluster in clusters:
            self.create_cluster(*cluster)
        for cluster in cluster_updates:
            self.update_cluster_nodes(*cluster)

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        print(f"\n{CC.OKBLUE} -- {CC.ENDC}Check if we need to cleanup hosts")
        delete_list = []
        for host, host_data in cmk_hosts.items():
            host_labels = host_data['extensions']['attributes'].get('labels',{})
            if host_labels.get('cmdb_syncer') == self.account_id:
                if host not in synced_hosts:
                    # Delete host

                    if app.config['CMK_BULK_DELETE_HOSTS']:
                        delete_list.append(host)
                        print(f"{CC.WARNING} *{CC.ENDC} Going to Delete host {host}")
                    else:
                        url = f"/objects/host_ocnfig/{host}"
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

#.
#   .-- Create Host


    def send_create_host(self, entries):
        """
        Send Process to create hosts
        """
        url = "/domain-types/host_config/actions/bulk-create/invoke"
        self.request(url, method="POST", data={'entries': entries})

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
            body['attributes'].update(additional_attributes)

        self.bulk_creates.append(body)
        print(f"{CC.OKBLUE} *{CC.ENDC} Add to Bulk List")


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
    def send_update_host(self, entries):
        """
        Send Update requests to CMK
        """

        url = "/domain-types/host_config/actions/bulk-update/invoke"
        self.request(url, method="PUT",
                     data={'entries': entries},
                    )

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
            # We may already got the Etag by the folder move action
            if not etag and not app.config['CMK_BULK_UPDATE_HOSTS']:
                etag = self.get_etag(db_host, "Update Host")

            update_url = f"objects/host_config/{db_host.hostname}"
            update_body = {
                'update_attributes': {},
            }

            if do_update_labels:
                update_body['labels'] = labels
            if do_update_attributes and additional_attributes:
                update_body['update_attributes'].update(additional_attributes)

            if do_remove_attributes and remove_attributes:
                update_body['remove_attributes'] = remove_attributes


            logger.debug(f"Syncer Update Body: {update_body}")


            # CHeckmk currently fails if you send labels and tags the same time
            # and you cant send update and remove attributes at the same time
            for what in ['attributes', 'update_attributes', 'remove_attributes', 'labels']:
                if what in update_body:
                    payload = {
                        what: update_body[what],
                    }
                    if what == 'labels':
                        payload = {
                            "update_attributes": {'labels': update_body[what]},
                        }

                    if not app.config['CMK_BULK_UPDATE_HOSTS']:
                        update_headers = {
                            'if-match': etag,
                        }
                        self.request(update_url, method="PUT",
                                     data=payload,
                                     additional_header=update_headers)
                        etag = self.get_etag(db_host, "After last Update")
                        print(f"{CC.OKGREEN} *{CC.ENDC} Updated Host in Checkmk")
                        print(f"   Reasons: {what}: {', '.join(update_reasons)}")
                    else:
                        payload['host_name'] = db_host.hostname
                        self.bulk_updates.append(payload)
                        print(f"{CC.OKBLUE} *{CC.ENDC} Add to Bulk Update List for {what} update")
            db_host.set_export_sync()


#.
