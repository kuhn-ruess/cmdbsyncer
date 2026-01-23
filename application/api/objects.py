"""
Objects Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from datetime import datetime
from mongoengine.errors import DoesNotExist

from flask import request, abort
from flask_restx import Namespace, Resource, reqparse, fields
from application.api import require_token
from application.models.host import Host
from application.plugins.checkmk.models import CheckmkFolderPool #@TODO pre_deletion method for Host so no import needed

from application.helpers.get_account import get_account_by_name, AccountNotFoundError

API = Namespace('objects')


def serialize_for_json(data):
    """
    Recursive function to convert datetime objects to ISO format strings
    to make the data JSON serializable
    """
    if isinstance(data, dict):
        return {key: serialize_for_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_for_json(item) for item in data]
    elif isinstance(data, datetime):
        return data.strftime('%Y-%m-%dT%H:%M:%SZ')
    return data


def build_host_dict(host_obj):
    """
    Build dict of an object which will be returned
    """
    host_dict = {}
    host_dict['hostname'] = host_obj.hostname

    # Ensure all values in labels and inventory are JSON serializable
    host_dict['labels'] = serialize_for_json(host_obj.get_labels())
    host_dict['inventory'] = serialize_for_json(host_obj.get_inventory())

    last_seen = False
    if host_obj.last_import_seen:
        last_seen = host_obj.last_import_seen.strftime('%Y-%m-%dT%H:%M:%SZ')
    host_dict['last_seen'] = last_seen

    last_update = False
    if host_obj.last_import_sync:
        last_update = host_obj.last_import_sync.strftime('%Y-%m-%dT%H:%M:%SZ')
    host_dict['last_update'] = last_update

    return host_dict


HOST = API.model(
    'host_object',
    {
        'account': fields.String(required=True),
        'labels': fields.Raw({}, required=True),
    },
)

HOST_BULK = API.model(
    'host_bulk',
    {
        'account': fields.String(required=True),
        'objects': fields.List(
            fields.Nested(
                API.model(
                    'host_bulk_item',
                    {
                        'hostname': fields.String(required=True),
                        'labels': fields.Raw({}, required=True),
                    }
                )
            ),
            required=True
        ),
    },
)

HOST_INVENTORY = API.model(
    'inventory_object',
    {
        'key': fields.String(required=True),
        'inventory': fields.Raw({}, required=True),
    },
)

HOST_INVENTORY_BULK = API.model(
    'inventory_bulk',
    {
        'inventories': fields.List(
            fields.Nested(
                API.model(
                    'inventory_bulk_item',
                    {
                        'hostname': fields.String(required=True),
                        'key': fields.String(required=True),
                        'inventory': fields.Raw({}, required=True),
                    }
                )
            ),
            required=True
        ),
    },
)


@API.route('/<hostname>')
class HostDetailApi(Resource):
    """Host Attributes """

    @require_token
    def get(self, hostname):
        """ Get Attributes of given Host """
        host_dict = {}
        try:
            host = Host.objects.get(hostname=hostname)
            return build_host_dict(host)
        except DoesNotExist:
            return {'error': "Host not found"}, 404
        return host_dict

    @require_token
    @API.expect(HOST, validate=True)
    def post(self, hostname):
        """ Create/ Update a Host Object"""
        req_json = request.json
        account = req_json['account']
        try:
            account_dict = get_account_by_name(account)
        except AccountNotFoundError:
            abort(400, "Account not found")
        labels = req_json['labels']
        host_obj = Host.get_host(hostname)
        host_obj.update_host(labels)
        do_save = host_obj.set_account(account_dict=account_dict)

        if do_save:
            status = 'account_conflict'
            status_code = 403
            host_obj.save()
        status = 'saved'
        status_code = 200

        return {'status': status}, status_code

    @require_token
    def delete(self, hostname):
        """ Delete Object """
        host_obj = Host.get_host(hostname, create=False)
        status = "not found"
        status_code = 404
        if host_obj:
            if folder := host_obj.folder:
                folder = CheckmkFolderPool.objects.get(folder_name__iexact=folder)
                if folder.folder_seats_taken > 0:
                    folder.folder_seats_taken -= 1
                    folder.save()
            status = "deleted"
            status_code = 200
            host_obj.delete()

        return {'status': status}, status_code

@API.route('/bulk')
class HostDetailBulkApi(Resource):
    """Host Bulk Attributes """

    @require_token
    @API.expect(HOST_BULK, validate=True)
    def post(self):
        """ Update of Hosts in BULK """
        req_json = request.json
        count = 0
        account = req_json['account']
        try:
            account_dict = get_account_by_name(account)
        except AccountNotFoundError:
            abort(400, "Account not found")
        not_save = []
        for api_host in req_json['objects']:
            hostname = api_host['hostname']
            labels = api_host['labels']
            host_obj = Host.get_host(hostname)
            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=account_dict)

            if do_save:
                host_obj.save()
                count += 1
            else:
                not_save.append(hostname)

        status = f'saved {count}'
        status_code = 200

        return {'status': status, 'not-saved': not_save}, status_code

@API.route('/<hostname>/inventory')
class HostDetailInventoryApi(Resource):
    """Host Attributes """

    @require_token
    @API.expect(HOST_INVENTORY, validate=True)
    def post(self, hostname):
        """ Update Inventory of Host Object """
        req_json = request.json
        key = req_json['key']
        inventory = req_json['inventory']
        host_obj = Host.get_host(hostname)
        host_obj.update_inventory(key, inventory)
        host_obj.save()
        status = 'saved'
        status_code = 200

        return {'status': status}, status_code

@API.route('/bulk/inventory')
class HostDetailInventoryBulkApi(Resource):
    """Host Attributes """

    @require_token
    @API.expect(HOST_INVENTORY_BULK, validate=True)
    def post(self):
        """ Update Inventories of Hosts in BULK """
        req_json = request.json
        count = 0
        for inv in req_json['inventories']:
            hostname = inv['hostname']
            key = inv['key']
            inventory = inv['inventory']
            host_obj = Host.get_host(hostname)
            host_obj.update_inventory(key, inventory)
            host_obj.save()
            count += 1
        status = f'saved {count}'
        status_code = 200

        return {'status': status}, status_code



parser = reqparse.RequestParser()
parser.add_argument('start', type=int, help='Pagination start')
parser.add_argument('limit', type=int, help='Pagination limit')

@API.route('/all')
@API.param('start', "Pagination start index")
@API.param('limit', "Pagination Limit")
class HostDetailListApi(Resource):
    """Host Attributes """

    @require_token
    def get(self):
        """ Get all Objects """
        results = []
        start = int(request.args['start'])
        limit = int(request.args['limit'])
        end = start+limit

        db_objecs = Host.objects(is_object__ne=True)
        total = db_objecs.count()
        for host in db_objecs[start:end]:
            results.append(build_host_dict(host))

        prev_start = max(start-limit, 0)
        links = {
            'next': f'/api/v1/objects/all?limit={limit}&start={end}',
            'prev': f'/api/v1/objects/all?limit={limit}&start={prev_start}',
        }
        if end >= total:
            del links['next']
        return {
            'results': results,
            'start': start,
            'limit': limit,
            'size': total,
            '_links': links, 
        }
