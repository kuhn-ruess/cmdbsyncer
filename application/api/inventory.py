"""
Inventory provider HTTP endpoints.

The cross-module provider registry (`application.modules.inventory`)
holds named providers. This namespace exposes them in the formats
external systems expect — currently the standard Ansible JSON shape
under `/api/v1/inventory/ansible/<provider>`.

Both the CLI (`cmdbsyncer inventory ansible <provider>`) and this HTTP
endpoint share `render_ansible_inventory`, so the data and the format
stay in lockstep regardless of how a consumer reaches them.
"""
from flask import request
from flask_restx import Namespace, Resource

from application.api import require_token
from application.modules.inventory import (
    list_inventory_providers,
    render_ansible_inventory,
)

API = Namespace('inventory', description='Cross-module inventory provider endpoints')


@API.route('/ansible')
class AnsibleProviderIndex(Resource):
    """List the providers the Ansible-format adapter can serve."""

    @require_token
    def get(self):
        """Names of all registered inventory providers."""
        return {'providers': list_inventory_providers()}


@API.route('/ansible/<provider>')
class AnsibleProviderInventory(Resource):
    """Full inventory for `provider`, in Ansible JSON shape.

    Pass `?host=NAME` to get a single host's vars dict instead of the
    full catalog — same contract Ansible expects from a dynamic
    inventory script.
    """

    @require_token
    def get(self, provider):
        """Render the provider in Ansible-format JSON."""
        host = request.args.get('host')
        result = render_ansible_inventory(provider, host=host)
        if result is None:
            return {'message': f'Unknown provider: {provider}'}, 404
        if result is False:
            return {'message': f'Host not found: {host}'}, 404
        return result
