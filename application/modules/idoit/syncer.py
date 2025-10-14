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


class SyncIdoit(Plugin):
    """
    i-doit sync options
    """

    category_cache = {}
    config = {}

#.
#   .-- Init
    def __init__(self):
        """
        Inital
        """

        self.log = log
        self.verify = not app.config.get("DISABLE_SSL_ERRORS")

#.
#.  .-- Get host data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the i-doit params
        """

        return self.actions.get_outcomes(db_host, attributes)

#.
#   . -- Request
    def request(self, data, method="POST"):
        """
        Handle request to i-doit
        """

        address = self.config["address"]
        url = f"{address}/src/jsonrpc.php"

        auth = HTTPBasicAuth(self.config["username"], self.config["password"])
        try:
            method = method.lower()

            logger.debug(f"Request ({method.upper()}) to {url}")
            logger.debug(f"Request JSON Body: {data}")

            if method == "post":
                #pylint: disable=missing-timeout
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
#   .-- Get object categories
    def get_object_categories(self, obj_id):
        """
        Get all needed categories for an object in i-doit
        """

        self.object_categories = self.config.get("object_categories", "")
        self.object_categories = [x.strip() for x in self.object_categories.split(",")]

        print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: "\
              f"Processing objects categories")

        for category in self.object_categories:
            json_data = {
                "id": 1,
                "version": "2.0",
                "method": "cmdb.category.read",
                "params": {
                    "apikey": self.config["password"],
                    "language": self.config.get("language", "en"),
                    "category": category,
                    "objID": obj_id,
                },
            }

            response = self.request(json_data)

            if "result" not in response.keys():
                continue

            elif not response["result"]:
                continue

            response = response["result"][0]
            cache_name = f"{obj_id}__{category}"

            if cache_name not in self.category_cache.keys():
                self.category_cache[cache_name] = response

            yield {cache_name: self.category_cache[cache_name]}

#.
#   .-- Get objects
    def get_objects(self, object_type="C__OBJTYPE__SERVER", get_categories=False):
        """
        Read full list of devices
        """

        print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: "\
              f"Read all objects from {object_type}")

        json_data = {
            "version": "2.0",
            "method": "cmdb.objects.read",
            "params": {
                "filter": {
                    "type": f"{object_type}",
                    "status": "C__RECORD_STATUS__NORMAL"
                },
                "apikey": self.config["password"],
                "language": self.config.get("language", "en")
            },
            "id": 1
        }

        servers = {}
        for server in self.request(json_data)["result"]:
            print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: "\
                  f"Processing host {server['title']}")

            title = server["title"]

            if get_categories:
                for result in self.get_object_categories(server["id"]):

                    for cat, values in result.items():
                        cat = cat.split("__")[-1].lower()

                        for key, value in values.items():
                            if isinstance(value, dict) and "title" in value.keys():
                                value = value["title"]

                            name = f"{cat}_{key}"
                            server[name] = value

            servers[title] = server

        return servers.items()

#.
#   .--- Get object payload
    def get_object_payload(self, db_host, rules):
        """
        Get basic object payload to create or update a object
        """

        object_type = rules.get("id_object_type", "C__OBJTYPE__SERVER")
        object_description = rules.get("id_object_description", "undefined")

        method = "cmdb.object.create"

        hostname = db_host.hostname
        payload =  {
           "version": "2.0",
           "method": method,
           "params": {
               "type": object_type,
               "title": hostname,
               "description": object_description,
               "apikey": self.config["password"],
               "language": self.config.get("language", "en"),
               "categories": rules.get("id_category", {})
           },
           "id": 1
        }

        return payload

#.
#   .--- Export hosts
    def export_hosts(self):
        """
        Update device table in i-doit
        """

        #pylint: disable=too-many-locals

        print(f"{CC.OKGREEN} -- {CC.ENDC}CACHE: Read all objects from i-doit")
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

            custom_rules = self.get_host_data(db_host, all_attributes["all"])
            if custom_rules.get("ignore_host"):
                continue

            print(f"\n{CC.HEADER}({process:.0f}%) {objectname}{CC.ENDC}")

            current_id = False
            if objectname not in current_idoit_objects:
                payload = self.get_object_payload(db_host,
                                                  custom_rules)

                print(f"{CC.OKBLUE} *{CC.ENDC} Create Host id {current_id}")

                self.request(payload)

            else:
                print(f"{CC.WARNING} *{CC.ENDC}  Host already existed")

#.
#   .--- Import hosts
    def import_hosts(self):
        """
        Import objects from i-doit
        """

        # loop for object type
        object_types = self.config.get("object_types", "")
        object_types = [x.strip() for x in object_types.split(",")]

        for object_type in object_types:

            if not object_type:
                continue

            print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: Processing {object_type}")

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
