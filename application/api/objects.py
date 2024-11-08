"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from mongoengine.errors import DoesNotExist

from flask import request
from flask_restx import Namespace, Resource, reqparse, fields
from application.api import require_token
from application.models.host import Host

from application.helpers.get_account import get_account_by_name

API = Namespace('objects')


def build_host_dict(host_obj):
    """
    Build dict of an object which will be returned
    """
    host_dict = {}
    host_dict['hostname'] = host_obj.hostname
    host_dict['labels'] = host_obj.get_labels()
    host_dict['inventory'] = host_obj.get_inventory()

    last_seen = False
    if host_obj.last_import_seen:
        last_seen = host_obj.last_import_seen.strftime('%Y-%m-%dT%H:%M:%SZ')
    host_dict['last_seen'] = last_seen

    last_update = False
    if host_obj.last_import_sync:
        last_update = host_obj.last_import_sync.strftime('%Y-%m-%dT%H:%M:%SZ')
    host_dict['last_update'] = last_update

    return host_dict

LABEL = API.model(
    'label',
    {
        'key': fields.String(required=True),
        'value': fields.String(required=True),
    },
)


HOST = API.model(
    'host_object',
    {
        'account': fields.String(required=True),
        'labels': fields.Raw({}, required=True),
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
        account_dict = get_account_by_name(account)
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
            status = "deleted"
            status_code = 200
            host_obj.delete()

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
