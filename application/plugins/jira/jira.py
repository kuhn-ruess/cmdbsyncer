"""
Import Jira Data
"""
#pylint: disable=too-many-locals
import requests
from application import app
from application import logger
from application.helpers.get_account import get_account_by_name
from application.models.host import Host
from application.modules.debug import ColorCodes


def import_jira(account):
    """
    Inner Import
    """
    verify = not app.config.get('DISABLE_SSL_ERRORS')
    config = get_account_by_name(account)
    page_size = config['page_size']
    user = config['username']
    password = config['password']

    # Platforms
    meta = {}
    meta_config = [
        #{'name': "platforms",
        # 'url': f"{config['address']}/it-platforms?page_size={page_size}",
        # 'attriubte': "platformKey"
        #},
        #{'name': "services",\
        # 'url': f"{config['address']}/it-services?page_size={page_size}",
        # 'attriubte': 'serviceName',
        #},
        {'name': "environment",
         'url': f"{config['address']}/environments?page_size={page_size}",
         'attriubte': 'identifier',
        }
    ]
    for what in meta_config:
        name = what['name']
        url = what['url']
        meta.setdefault(name, {})
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Request: Read {name} Data")
        response = requests.get(url, auth=(user, password), timeout=30, verify=verify)
        meta[name] = {x['key']: x[what['attriubte']] for x in response.json()['data']}

    url = f"{config['address']}/servers?pageSize={page_size}"
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Request: Read all Hosts")
    response = requests.get(url, auth=(user, password), timeout=30, verify=verify)
    all_data = response.json()['data']
    total = len(all_data)
    counter = 0
    for host in all_data:
        # pylint: disable=logging-fstring-interpolation
        logger.debug(f'Host Data: {host}')
        counter += 1
        hostname = host['name']
        process = 100.0 * counter / total
        print(f"{ColorCodes.OKGREEN}({process:.0f}%){ColorCodes.ENDC} {hostname}")
        host_obj = Host.get_host(hostname)
        host_obj.raw = str(host)
        del host['name']

        attributes = {}
        for attr, attr_value in host.items():
            if attr in [x['name'] for x in meta_config]:
                attributes[attr] = meta[attr][attr_value['id']]
            elif isinstance(attr_value, dict):
                attributes[attr] = attr_value['value']
            elif isinstance(attr_value, list):
                for idx, value in enumerate(attr_value):
                    attributes[f'{attr}_{idx}'] = value['value']
        host_obj.update_host(attributes)
        do_save = host_obj.set_account(account_dict=config)
        if do_save:
            host_obj.save()