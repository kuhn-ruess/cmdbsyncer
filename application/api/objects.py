"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from mongoengine.errors import DoesNotExist

from flask import request
from flask_restx import Namespace, Resource, reqparse
from application.api import require_token
from application.models.host import Host

API = Namespace('objects')


def build_host_dict(host_obj):
    """
    Build dict of an object which will be returned
    """
    host_dict = {}
    host_dict['hostname'] = host_obj.hostname
    host_dict['labels'] = host_obj.get_labels()
    host_dict['inventory'] = host_obj.get_inventory()
    host_dict['last_seen'] = host_obj.last_import_seen.strftime('%Y-%m-%dT%H:%M:%SZ')
    return host_dict



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
