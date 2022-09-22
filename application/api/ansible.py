"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from flask_restx import Namespace, Resource
from application.plugins_shipped.ansible import get_host_inventory, get_full_inventory
from application.api import require_token

API = Namespace('ansible')


@API.route('/')
class AnsibleApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """ Return complete Ansible Inventory """
        return get_full_inventory()

@API.route('/<hostname>')
class AnsibleDetailApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self, hostname):
        """ Return Hosts Ansible Inventory """
        return get_host_inventory(hostname)
