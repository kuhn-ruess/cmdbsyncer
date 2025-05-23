"""
Alle Stuff shared by the plugins
"""
#pylint: disable=too-few-public-methods
#pylint: disable=logging-fstring-interpolation
from datetime import datetime
import time
import json as mod_json
import atexit

from pprint import pformat
from collections import namedtuple

from mongoengine.errors import DoesNotExist
import requests
from application import logger, app, log
from application.modules.custom_attributes.models import CustomAttributeRule as \
    CustomAttributeRuleModel
from application.modules.custom_attributes.rules import CustomAttributeRule

from application.modules.debug import attribute_table

from syncerapi.v1 import (
    get_account,
    Host,
    cc,
)

class ResponseDataException(Exception):
    """
    Raise in case of invalid responses
    """


class Plugin():
    """
    Base Class for all Plugins
    """
    rewrite = False
    filter = False
    custom_attributes = False
    debug = False
    account = False
    verify = True

    dry_run = False
    save_requests = False

    config = None
    log_details = None


    debug_lines = [] # Used for GUI Debuging


    name = "Undefined"
    source = None

    def __init__(self, account=False):
        """
        Intit
        """
        self.start_time = time.time()
        self.log_details = []
        self.log_details.append(('started', datetime.now()))
        if account:
            self.config = get_account(account)
            if not self.config:
                raise ValueError("Account Invalid or not found")
            self.account_name = self.config['name']
            self.account_id = str(self.config['_id'])
            self.log_details.append(('Account', self.config['name']))
            self.verify = self.config.get('verify_cert')

        if verify := app.config.get('DISABLE_SSL_ERRORS'):
            # Legacy Behavior -> Global Setting Overwrite. Deprecated start v3.8.2
            self.verify = not app.config.get('DISABLE_SSL_ERRORS')


        if not self.source:
            self.source = self.__class__.__qualname__.replace('.','')


        atexit.register(self.save_log)

    def save_log(self):
        """
        Save Details to log
        """
        duration = time.time() - self.start_time
        self.log_details.append(('duration', duration))
        self.log_details.append(('ended', datetime.now()))

        log.log(self.name, source=self.source, details=self.log_details)




    def inner_request(self, method, url, data=None, json=None, headers=None, auth=None, params=None, cert=None):
        """
        Requst Module for all HTTP Requests
        by Plugin
        """
        logger.debug('\n************ HTTP DEBUG ************')
        logger.debug(f"Request ({method.upper()}) to {url}")

        method = method.lower()
        payload = {
            'verify': self.verify,
            'timeout': app.config['HTTP_REQUEST_TIMEOUT'],
        }

        if headers:
            payload['headers'] = headers
        if auth:
            payload['auth'] = auth
        if json:
            payload['json'] = json
        if data:
            payload['data'] = data
        if params:
            payload['params'] = params
        if cert:
            payload['cert'] = cert

        log_dict = payload.copy()
        if 'json' in payload:
            log_dict['json'] = mod_json.dumps(payload['json'])

        logger.debug(f"Payload: {log_dict}")

        if path := self.save_requests:
            #pylint: disable=consider-using-with
            open(path, "a", encoding="utf-8").write(f"{method}||{url}||{payload}\n")

        if self.dry_run:
            logger.info(f"Body: {pformat(data)}")
            Struct = namedtuple('response', ['status_code', 'headers', 'json'])
            json_obj = lambda: {} #pylint: disable=unnecessary-lambda-assignment
            if method != 'get':
                return Struct(status_code=200, headers={}, json=json_obj)


        #match method:
        #    case "get":
        #        resp = requests.get(url, **payload)
        #    case 'post':
        #        resp = requests.post(url, **payload)
        #    case 'patch':
        #        resp = requests.patch(url, **payload)
        #    case 'put':
        #        resp = requests.put(url, **payload)
        #    case 'delete':
        #        resp = requests.delete(url, **payload)
        #    case 'head':
        #        resp = requests.head(url, **payload)
        #    case 'options':
        #        resp = requests.options(url, **payload)
        # Python pre 3.10 suppport.....:
        max_retries = app.config['HTTP_MAX_RETRIES']
        retry_wait = app.config['HTTP_REPEAT_TIMEOUT']
        resp = {}
        for attempt in range(1, max_retries+1):
            try:
                if method == "get":
                    resp = requests.get(url, **payload)
                elif method == 'post':
                    resp = requests.post(url, **payload)
                elif method == 'patch':
                    resp = requests.patch(url, **payload)
                elif method == 'put':
                    resp = requests.put(url, **payload)
                elif method == 'delete':
                    resp = requests.delete(url, **payload)
                elif method ==  'head':
                    resp = requests.head(url, **payload)
                elif method ==  'options':
                    resp = requests.options(url, **payload)
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                print(f"Try {attempt} of {max_retries} failed: {e}")
                if attempt < max_retries:
                    print(f"Timeout for {retry_wait} Secounds\033[5m...\033[0m")
                    time.sleep(retry_wait)
                else:
                    raise

        try:
            logger.debug(f"Response Json: {mod_json.dumps(resp.json())}")
        except requests.exceptions.JSONDecodeError:
            logger.debug(f"Response Text: {pformat(resp.text)}")
        except AttributeError:
            logger.debug(f"Response Raw: {pformat(resp)}")
        return resp


    def init_custom_attributes(self):
        """
        Load Rules for custom Attributes
        """
        self.custom_attributes = CustomAttributeRule()
        self.custom_attributes.debug = self.debug
        self.custom_attributes.rules = \
                        CustomAttributeRuleModel.objects(enabled=True).order_by('sort_field')


    def get_attributes(self, db_host, cache):
        """
        Return Host Attributes or False if Host should be ignored
        """
        # Get Attributes
        if cache:
            cache += "_hostattribute"
            db_host.cache.setdefault(cache, {})
            if 'attributes' in db_host.cache[cache]:
                logger.debug(f"Using Attribute Cache for {db_host.hostname}")
                if 'ignore_host' in db_host.cache[cache]['attributes']['filtered']:
                    return False
                return db_host.cache[cache]['attributes']
        attributes = {}
        attributes.update(db_host.labels.items())
        attributes.update(db_host.inventory.items())

        self.init_custom_attributes()
        attributes.update(self.custom_attributes.get_outcomes(db_host, attributes))

        attributes_filtered = {}
        if self.rewrite:
            for rewrite, value in self.rewrite.get_outcomes(db_host, attributes).items():
                realname = rewrite[4:]
                if rewrite.startswith('add_'):
                    attributes[realname] = value
                elif rewrite.startswith('del_'):
                    try:
                        del attributes[realname]
                    except KeyError:
                        continue
        # This is used that we have this varialbe in all Jinja Contexts
        attributes['HOSTNAME'] = db_host.hostname
        data = {
            'all': attributes,
            'filtered': attributes_filtered,
        }

        if self.filter:
            attributes_filtered = self.filter.get_outcomes(db_host, attributes)
            data['filtered'] = attributes_filtered
            if attributes_filtered.get('ignore_host') and cache:
                db_host.cache[cache]['attributes'] = data
                db_host.save()
                return False

        if cache:
            db_host.cache[cache]['attributes'] = data
            db_host.save()
        return data

#   .-- Get Host Data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)
#.

    def debug_rules(self, hostname, model):
        """
        Debug Mode to see Rule outcomes.
        Used with --debug-rules switch
        """
        if self.rewrite:
            self.rewrite.debug = True
        self.actions.debug = True
        self.config = {
            '_id': "debugmode",
        }
        try:
            db_host = Host.objects.get(hostname=hostname)
            for key in list(db_host.cache.keys()):
                if key.lower().startswith(model):
                    del db_host.cache[key]
            if "CustomAttributeRule" in db_host.cache:
                del db_host.cache['CustomAttributeRule']
            db_host.save()
        except DoesNotExist:
            print(f"{cc.FAIL}Host not Found{cc.ENDC}")
            return

        attributes = self.get_attributes(db_host, False)

        if not attributes:
            print(f"{cc.FAIL}THIS HOST IS IGNORED BY RULE{cc.ENDC}")
            return

        extra_attributes = self.get_host_data(db_host, attributes['all'])
        attribute_table("Attributes by Rule ", extra_attributes)
