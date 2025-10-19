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

        object_categories = self.config.get("object_categories", "")
        object_categories = [x.strip() for x in object_categories.split(",")]

        for category in object_categories:
            json_data = {
                "id": 1,
                "version": "2.0",
                "method": "cmdb.category.read",
                "params": {
                    "apikey": self.config["api_token"],
                    "language": self.config["language"],
                    "category": category,
                    "objID": obj_id,
                },
            }

            response = self.request(json_data)

            if "result" not in response.keys():
                continue

            elif not response["result"]:
                continue

            response = response["result"]
            cache_name = f"{obj_id}__{category}"
            name = category.split("_")[-1].lower()

            if len(response) == 1:
                counter = ""
            else:
                counter = "_1"

            for item in response:
                data = {}

                for key, values in item.items():

                    if isinstance(values, dict):

                        for item, value in values.items():
                            data[f"{name}{counter}_{key}_{item}"] = value

                    elif isinstance(values, list):

                        if len(values) == 1:
                            item_counter = ""

                        else:
                            item_counter = "_1"

                        for entry in values:

                            for item, value in entry.items():
                                data[f"{name}{counter}_{key}_{item}{item_counter}"] = value

                            if item_counter:
                                item_counter = f"_{int(item_counter[-1]) +1}"

                    else:
                        data[f"{name}{counter}_{key}"] = values

                if counter:
                    counter = f"_{int(counter[-1]) + 1}"

                if cache_name not in self.category_cache.keys():
                    self.category_cache[cache_name] = data

                else:
                    self.category_cache[cache_name].update(data)

            yield {cache_name: self.category_cache[cache_name]}

#.
#   .-- Get objects
    def get_objects(self, object_type="C__OBJTYPE__SERVER", get_categories=False):
        """
        Read full list of devices
        """

        json_data = {
            "version": "2.0",
            "method": "cmdb.objects.read",
            "params": {
                "filter": {
                    "type": f"{object_type}",
                    "status": "C__RECORD_STATUS__NORMAL"
                },
                "apikey": self.config["api_token"],
                "language": self.config["language"]
            },
            "id": 1
        }

        servers = {}
        for server in self.request(json_data)["result"]:
            states = self.config.get("filter_cmdb_status", "")

            if states.strip().endswith(","):
                states = states[:-1]

            states = [x.strip() for x in states.split(",")]

            if server["cmdb_status"] not in map(int, states):
                continue

            title = server["title"]

            if get_categories:
                for result in self.get_object_categories(server["id"]):

                    for cat, values in result.items():
                        for name, value in values.items():
                            server[name] = value

            if "True" == self.config["filter_monitoring_status"].capitalize():
                if "monitoring_active_value" in server and "1" == server["monitoring_active_value"]:
                    servers[title] = server
            else:
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
               "apikey": self.config["api_token"],
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

            print(f"{CC.OKGREEN} -- {CC.ENDC}i-doit: Processing object type {object_type}")

            if objects := self.get_objects(object_type=object_type, get_categories=True):

                for device, labels in objects:
                    host_obj = Host.get_host(device)

                    print(f"{CC.HEADER}Process Device: {device}{CC.ENDC}")

                    host_obj.update_host(labels)
                    do_save = host_obj.set_account(account_dict=self.config)

                    if do_save:
                        host_obj.save()

            else:
                print(f"{CC.HEADER}no devices found{CC.ENDC}")

            print()
