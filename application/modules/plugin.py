"""
Alle Stuff shared by the plugins
"""
#pylint: disable=too-few-public-methods
#pylint: disable=logging-fstring-interpolation
from datetime import datetime
import time
import atexit

from pprint import pformat
from collections import namedtuple
import requests
from application import logger, app, log
from application.modules.custom_attributes.models import CustomAttributeRule as \
    CustomAttributeRuleModel
from application.modules.custom_attributes.rules import CustomAttributeRule

from syncerapi.v1 import (
    get_account,
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
    source = "Undefined"

    def __init__(self, account=False):
        self.start_time = time.time()
        self.log_details = []
        self.log_details.append(('started', datetime.now()))
        if account:
            self.config = get_account(account)
            if not self.config:
                raise ValueError("Account Invalid or not found")
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')


        atexit.register(self.save_log)

    def save_log(self):
        """
        Save Details to log
        """
        duration = time.time() - self.start_time
        self.log_details.append(('duration', duration))
        self.log_details.append(('ended', datetime.now()))

        log.log(self.name, source=self.source, details=self.log_details)


    def inner_request(self, method, url, data=None, headers=None, auth=None):
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

        if headers and headers.get('Content-Type') == "application/json" and data:
            payload['json'] = data
        elif data:
            payload['params'] = data

        logger.debug(f"Payload: {pformat(payload)}")

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

        try:
            logger.debug(f"Response Json: {pformat(resp.json())}")
        except requests.exceptions.JSONDecodeError:
            logger.debug(f"Response Text: {pformat(resp.text)}")
        return resp


    def init_custom_attributes(self):
        """
        Load Rules for custom Attributes
        """
        self.custom_attributes = CustomAttributeRule()
        self.custom_attributes.debug = self.debug
        self.custom_attributes.rules = \
                        CustomAttributeRuleModel.objects(enabled=True).order_by('sort_field')

    def get_host_attributes(self, db_host, cache):
        """
        Return Host Attributes or False if Host should be ignored
        """
        # Get Attributes
        cache += "_hostattribute"
        db_host.cache.setdefault(cache, {})
        if 'attributes' in db_host.cache[cache]:
            logger.debug(f"Using Attribute Cache for {db_host.hostname}")
            if 'ignore_host' in db_host.cache[cache]['attributes']['filtered']:
                return False
            return db_host.cache[cache]['attributes']
        attributes = {}
        attributes.update({x:y for x,y in db_host.labels.items() if y})
        attributes.update({x:y for x,y in db_host.inventory.items() if y})

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
        data = {
            'all': attributes,
            'filtered': attributes_filtered,
        }

        if self.filter:
            attributes_filtered = self.filter.get_outcomes(db_host, attributes)
            data['filtered'] = attributes_filtered
            if attributes_filtered.get('ignore_host'):
                db_host.cache[cache]['attributes'] = data
                db_host.save()
                return False

        db_host.cache[cache]['attributes'] = data
        db_host.save()
        return data
