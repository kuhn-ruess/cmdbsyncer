"""
Sync objects with i-doit
"""
#pylint: disable=no-member, too-many-locals, import-error
import requests
from requests.auth import HTTPBasicAuth

from application.models.host import Host
from application import app, log, logger
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)


CATEGORY_TEMPLATES = {
    'C__CATG__MODEL' : {'key': 'manufacturer'},
    'C__CATG__CPU' : {},
    'C__CATG__IP' : {},
}


class SyncIdoit(Plugin):
    """
    i-doit sync options
    """

    category_cache = {}
    config = {}

#   .-- Init
    def __init__(self):
        """
        Inital
        """

        self.log = log
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')

    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the idoit params
        """

        return self.actions.get_outcomes(db_host, attributes)
#.
#   . -- Request
    def request(self, data, method='POST'):
        """
        Handle request to i-doit
        """

        address = self.config['address']
        url = f"{address}/src/jsonrpc.php"

        auth = HTTPBasicAuth(self.config['username'], self.config['password'])
        try:
            method = method.lower()
            logger.debug(f"Request ({method.upper()}) to {url}")
            logger.debug(f"Request Json Body: {data}")
            #pylint: disable=missing-timeout
            if method == 'post':
                response = requests.post(url, auth=auth, json=data)

            logger.debug(f"Response Text: {response.text}")
            if response.status_code == 403:
                raise Exception("Invalid login, you may need to create a login token")
            try:
                response_json = response.json()
            except:
                raise
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}
        return response_json
#.
#   .-- Get I-Doit Category
    def get_object_categories(self, obj_id):
        """
        Get all Categories for a Object in I-Doit
        {'id': 1,
         'jsonrpc': '2.0',
         'result': {'catg': [{'const': 'C__CATG__RELATION',
                              'id': '82',
                              'multi_value': '1',
                              'source_table': 'isys_catg_relation',
                              'title': 'Relationship'},
                             {'const': 'C__CATG__GLOBAL',
                              'id': '1',
                              'multi_value': '0',
                              'source_table': 'isys_catg_global',
                              'title': 'General'},
                             {'const': 'C__CATG__LOGBOOK',
                              'id': '22',
                              'multi_value': '1',
                              'source_table': 'isys_catg_logb',
                              'title': 'Logbook'}],
                    'cats': [{'const': 'C__CATS__REPLICATION',
                              'id': '71',
                              'multi_value': '0',
                              'source_table': 'isys_cats_replication_list',
                              'title': 'Replication'},
                             {'const': 'C__CATS__REPLICATION_PARTNER',
                              'id': '72',
                              'multi_value': '1',
                              'parent': '71',
                              'source_table': 'isys_cats_replication_partner_list',
                              'title': 'Replication partner'}]}}
        """
        json_data = {
            'id': 1,
            'version': '2.0',
            'method': 'cmdb.object_type_categories.read',
            'params': {
                'apikey': self.config['password'],
                'language': 'de',
                'type': obj_id,
            },
        }

        response = self.request(json_data)["result"]

        for cat in response['catg']:
            if cat['const'] not in CATEGORY_TEMPLATES.keys():
                continue

            #cache_name = f"{cat['id']}_{cat['const']}"
            #if cache_name not in self.category_cache:
            #    self.category_cache[cache_name] = \
            #            self.get_category_attributes(obj_id, cat['const'])
            #    self.category_cache['const'] = cat['const']

            #yield self.category_cache[cache_name]
            yield self.get_category_attributes(obj_id, cat['const'])

#.
#   .-- Get I-Doit Category Attributes
    def get_category_attributes(self, obj_id, const_id):
        """
        Get the the Attributes for a Category
        """
        json_data = {
            'id': 1,
            'version': '2.0',
            'method': 'cmdb.category.read',
            'params': {
                'apikey': self.config['password'],
                'language': 'de',
                'category': const_id,
                'objID': obj_id,
            },
        }
        response = self.request(json_data)

        if 'result' in response:
            return response['result']
        return {}
#.
#   .-- Get I-doit Objects
    def get_objects(self, object_type="C__OBJTYPE__SERVER", get_categories=False):
        """
        Read full list of devices
        """

        print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: "\
              f"Read all object from {object_type}")

        json_data = {
            "version": "2.0",
            "method": "cmdb.objects.read",
            "params": {
                "filter": {
                    "type": f"{object_type}",
                    "status": "C__RECORD_STATUS__NORMAL"
                },
                "apikey": self.config["password"],
                "language": "de"
            },
            "id": 1
        }

        servers = {}
        for server in self.request(json_data)['result']:
            logger.debug(f"server: {server}")

            title = server['title']

            if get_categories:
                categories = [x for x in self.get_object_categories(server['id']) if x]
                server['categories'] = categories

            servers[title] = server

        return servers.items()
#.
#   .--- Get Object Payload

    def get_object_payload(self, db_host, rules):
        """
        Get the Basic Object Payload to create or Update a object
        """

        object_type = rules.get('id_object_type', 'C__OBJTYPE__SERVER')
        object_description = rules.get('id_object_description', 'undefined')

        method = "cmdb.object.create"

        hostname = db_host.hostname
        payload =  {
           "version": "2.0",
           "method": method,
           "params": {
               "type": object_type,
               "title": hostname,
               "description": object_description,
               "apikey": self.config.get("password", "DEFINE API TOKEN"),
               "language": "de",
               "categories": rules.get('id_category', {})
           },
           # TENANT-ID
           "id": 1
        }

        return payload
#.
#   .--- Export Hosts
    def export_hosts(self):
        """
        Update Devices Table in Idoit
        """

        #pylint: disable=too-many-locals

        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all objects from I-doit")
        current_idoit_objects = dict(self.get_objects())

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Start Sync")
        db_objects = Host.get_export_hosts()
        total = len(db_objects)
        counter = 0
        found_hosts = []

        for db_host in db_objects:
            objectname = db_host.hostname
            counter += 1
            process = 100.0 * counter / total

            all_attributes = self.get_attributes(db_host, 'idoit')
            if not all_attributes:
                continue

            found_hosts.append(objectname)

            custom_rules = self.get_host_data(db_host, all_attributes['all'])
            if custom_rules.get('ignore_host'):
                continue

            print(f"\n{CC.HEADER}({process:.0f}%) {objectname}{CC.ENDC}")
            #current_idoit_object = current_idoit_objects[objectname]

            current_id = False
            if objectname not in current_idoit_objects:
                payload = self.get_object_payload(db_host,
                                                  custom_rules)
                print(f"{CC.OKBLUE} *{CC.ENDC} Create Host id {current_id}")
                self.request(payload)
            else:
                print(f"{CC.WARNING} *{CC.ENDC}  Host already existed")


#.
#   .--- Import Hosts
    def import_hosts(self):
        """
        Import objects from i-doit
        """

        # loop for object type
        object_types = self.config.get("object_types", "")
        object_types = [x.strip() for x in object_types.split(",")]

        for object_type in object_types:
            # get objects from types
            if objects := self.get_objects(object_type=object_type, get_categories=True):

                for device, labels in objects:
                    host_obj = Host.get_host(device)
                    print(f"\n{CC.HEADER}Process Device: {device}{CC.ENDC}")
                    host_obj.update_host(labels)
                    do_save = host_obj.set_account(account_dict=self.config)

                    if do_save:
                        host_obj.save()

            else:
                print(f"\n{CC.HEADER}no devices found{CC.ENDC}")
