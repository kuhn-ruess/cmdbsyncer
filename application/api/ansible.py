"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from flask_restx import Namespace, Resource
from application.api import require_token
from application.modules.ansible.syncer import SyncAnsible
from application.plugins.ansible import load_rules

API = Namespace('ansible')


@API.route('/')
class AnsibleApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """ Return complete Ansible Inventory """
        rules = load_rules()
        syncer = SyncAnsible()
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']
        syncer.actions = rules['actions']
        return syncer.get_full_inventory()

@API.route('/<hostname>')
class AnsibleDetailApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self, hostname):
        """ Return Hosts Ansible Inventory """
        rules = load_rules()
        syncer = SyncAnsible()
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']
        syncer.actions = rules['actions']
        return syncer.get_host_inventory(hostname)
