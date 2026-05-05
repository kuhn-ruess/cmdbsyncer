"""
Objects API.

CRUD over hosts and per-host inventory data. Authenticated via
``@require_token`` — a user with ``api_roles = ['objects']`` (or
``'all'``) can call this namespace. Hosts are bound to an account on
create/update; inventory writes never auto-create hosts.
"""
from datetime import datetime
from mongoengine.errors import DoesNotExist

from flask import request, abort
from flask_restx import Namespace, Resource, reqparse, fields
from application.api import require_token
from application.models.host import Host
# @TODO pre_deletion method for Host so no import needed
from application.plugins.checkmk.models import CheckmkFolderPool

from application.helpers.get_account import get_account_by_name, AccountNotFoundError
from application.helpers.mongo_keys import validate_mongo_key, validate_mongo_keys

API = Namespace(
    'objects',
    description='Read, create, update and delete host objects + inventory.',
)


def serialize_for_json(data):
    """
    Recursive function to convert datetime objects to ISO format strings
    to make the data JSON serializable
    """
    if isinstance(data, dict):
        return {key: serialize_for_json(value) for key, value in data.items()}
    if isinstance(data, list):
        return [serialize_for_json(item) for item in data]
    if isinstance(data, datetime):
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

HOST = API.model('host_object', {
    'account': fields.String(required=True,
                             description='Account name that owns the host. '
                                         'Must exist; an unknown account '
                                         'returns 400.'),
    'labels': fields.Raw(required=True,
                         description='Flat key/value attributes for the host. '
                                     'Empty object is valid.'),
})

HOST_BULK_ITEM = API.model('host_bulk_item', {
    'hostname': fields.String(required=True),
    'labels': fields.Raw(required=True,
                         description='Flat key/value attributes.'),
})

HOST_BULK = API.model('host_bulk', {
    'account': fields.String(required=True,
                             description='Account that owns every host '
                                         'in this batch.'),
    'objects': fields.List(fields.Nested(HOST_BULK_ITEM), required=True),
})

HOST_INVENTORY = API.model('inventory_object', {
    'key': fields.String(required=True,
                         description='Top-level inventory key '
                                     '(e.g. "checkmk", "netbox").'),
    'inventory': fields.Raw(required=True,
                            description='Nested inventory payload for *key*. '
                                        'Mongo-key constraints apply: no '
                                        'leading $ or dotted keys.'),
})

HOST_INVENTORY_BULK_ITEM = API.model('inventory_bulk_item', {
    'hostname': fields.String(required=True),
    'key': fields.String(required=True),
    'inventory': fields.Raw(required=True),
})

HOST_INVENTORY_BULK = API.model('inventory_bulk', {
    'inventories': fields.List(fields.Nested(HOST_INVENTORY_BULK_ITEM),
                               required=True),
})

HOST_RESPONSE = API.model('host_response', {
    'hostname': fields.String,
    'labels': fields.Raw(description='Resolved labels (datetimes serialized '
                                     'as ISO strings).'),
    'inventory': fields.Raw(description='Resolved inventory.'),
    'last_seen': fields.String(example='2026-04-26T17:55:00Z',
                               description='Last time this host was seen by '
                                           'an importer (ISO-8601 UTC), or '
                                           '``false`` if never imported.'),
    'last_update': fields.String(example='2026-04-26T17:55:00Z',
                                 description='Last time the host record was '
                                             'changed by an importer.'),
})

STATUS = API.model('status', {
    'status': fields.String(example='saved'),
})

BULK_STATUS = API.model('bulk_status', {
    'status': fields.String(example='saved 12'),
    'not-saved': fields.List(fields.String,
                             description='Hostnames that were skipped — '
                                         'usually because the host is already '
                                         'bound to a different account.'),
})

INVENTORY_BULK_STATUS = API.model('inventory_bulk_status', {
    'status': fields.String(example='saved 12'),
    'not-found': fields.List(fields.String,
                             description='Hostnames that did not exist; '
                                         'inventory writes never auto-create '
                                         'a host.'),
})

ERROR = API.model('error', {
    'error': fields.String(description='Human-readable error message'),
})

LIST_LINKS = API.model('list_links', {
    'next': fields.String(description='URL of the next page; absent on the '
                                      'last page.'),
    'prev': fields.String(description='URL of the previous page.'),
})

LIST_RESPONSE = API.model('list_response', {
    'results': fields.List(fields.Nested(HOST_RESPONSE)),
    'start': fields.Integer(description='Echo of the start cursor.'),
    'limit': fields.Integer(description='Echo of the page size.'),
    'size': fields.Integer(description='Total number of host objects '
                                       '(non-objects only).'),
    '_links': fields.Nested(LIST_LINKS),
})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@API.route('/<hostname>')
@API.param('hostname', 'Host name (case-sensitive, must be a valid hostname).')
class HostDetailApi(Resource):
    """Single-host CRUD."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Resolved host attributes + inventory.', HOST_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'No host with that name exists.', ERROR)
    @require_token
    def get(self, hostname):
        """Return the labels, inventory and last-seen timestamps for *hostname*."""
        try:
            host = Host.objects.get(hostname=hostname)
            return build_host_dict(host)
        except DoesNotExist:
            return {'error': "Host not found"}, 404

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(HOST, validate=True)
    @API.response(200, 'Host saved.', STATUS)
    @API.response(400, 'Account unknown or label payload invalid.', ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(403, 'Host already bound to a different account.', STATUS)
    @require_token
    def post(self, hostname):
        """Create or update a host. Binds the host to the given account.

        Hosts already bound to a different account return ``403`` —
        re-binding is a privileged operation done from the admin UI.
        """
        req_json = request.json
        account = req_json['account']
        try:
            account_dict = get_account_by_name(account)
        except AccountNotFoundError:
            abort(400, "Account not found")
        labels = req_json['labels']
        host_obj = Host.get_host(hostname)
        try:
            host_obj.update_host(labels)
        except ValueError as exc:
            abort(400, str(exc))
        do_save = host_obj.set_account(account_dict=account_dict)

        if not do_save:
            return {'status': 'account_conflict'}, 403

        host_obj.save()
        return {'status': 'saved'}, 200

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Host deleted.', STATUS)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'No host with that name exists.', STATUS)
    @require_token
    def delete(self, hostname):
        """Delete the host. If it occupied a Checkmk folder pool seat, the
        seat is freed."""
        host_obj = Host.get_host(hostname, create=False)
        status = "not found"
        status_code = 404
        if host_obj:
            if folder := host_obj.folder:
                try:
                    pool = CheckmkFolderPool.objects.get(folder_name__iexact=folder)
                except DoesNotExist:
                    pool = None
                if pool and pool.folder_seats_taken > 0:
                    pool.folder_seats_taken -= 1
                    pool.save()
            status = "deleted"
            status_code = 200
            host_obj.delete()

        return {'status': status}, status_code


@API.route('/bulk')
class HostDetailBulkApi(Resource):
    """Batched host create/update."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(HOST_BULK, validate=True)
    @API.response(200, 'Per-host save outcome. Hostnames that conflicted '
                       'with another account are listed in ``not-saved``.',
                  BULK_STATUS)
    @API.response(400, 'Account unknown or label payload invalid for an item.',
                  ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def post(self):
        """Create or update many hosts under a single account.

        Items that fail account binding are reported in ``not-saved`` —
        the rest are persisted; the call does not abort on per-item
        conflicts.
        """
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
            try:
                host_obj.update_host(labels)
            except ValueError as exc:
                abort(400, str(exc))
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
@API.param('hostname', 'Existing host name. Inventory writes never '
                       'auto-create a host.')
class HostDetailInventoryApi(Resource):
    """Per-host inventory write."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(HOST_INVENTORY, validate=True)
    @API.response(200, 'Inventory saved.', STATUS)
    @API.response(400, 'Inventory key or payload rejected by Mongo-key rules.',
                  ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'Host does not exist; inventory writes never create one.',
                  STATUS)
    @require_token
    def post(self, hostname):
        """Replace the inventory section identified by ``key`` on *hostname*."""
        req_json = request.json
        key = req_json['key']
        inventory = req_json['inventory']
        # Inventory writes must not create hosts — that path has no account
        # binding or hostname validation. Host creation goes through the
        # primary /<hostname> endpoint which requires an account.
        host_obj = Host.get_host(hostname, create=False)
        if not host_obj:
            return {'status': 'not found'}, 404
        try:
            host_obj.update_inventory(key, inventory)
        except ValueError as exc:
            abort(400, str(exc))
        host_obj.save()
        status = 'saved'
        status_code = 200

        return {'status': status}, status_code


@API.route('/bulk/inventory')
class HostDetailInventoryBulkApi(Resource):
    """Batched inventory write."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(HOST_INVENTORY_BULK, validate=True)
    @API.response(200, 'Per-host outcome. Unknown hostnames are returned in '
                       '``not-found``; the rest are saved.',
                  INVENTORY_BULK_STATUS)
    @API.response(400, 'A key or inventory payload was rejected. Items are '
                       'pre-validated, so the call aborts before any save.',
                  ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def post(self):
        """Replace inventory sections on many hosts in one call.

        Every payload item is validated upfront; one bad key aborts the
        whole batch so partial writes can't leave the DB inconsistent.
        Unknown hostnames are not an error — they're collected and
        returned in ``not-found``.
        """
        req_json = request.json
        # Pre-validate every item so a bad key later in the payload cannot
        # leave earlier items already persisted. Model-level validation
        # still runs per update; this pre-pass just moves the failure
        # upstream of any save().
        for inv in req_json['inventories']:
            try:
                validate_mongo_key(inv['key'], "inventory")
                validate_mongo_keys(inv['inventory'], "inventory")
            except ValueError as exc:
                abort(400, str(exc))
        count = 0
        not_found = []
        for inv in req_json['inventories']:
            hostname = inv['hostname']
            key = inv['key']
            inventory = inv['inventory']
            # See single-host variant: no implicit host creation here.
            host_obj = Host.get_host(hostname, create=False)
            if not host_obj:
                not_found.append(hostname)
                continue
            host_obj.update_inventory(key, inventory)
            host_obj.save()
            count += 1
        status = f'saved {count}'
        status_code = 200

        return {'status': status, 'not-found': not_found}, status_code


parser = reqparse.RequestParser()
parser.add_argument('start', type=int, help='Pagination start')
parser.add_argument('limit', type=int, help='Pagination limit')


MAX_PAGE_LIMIT = 10000


@API.route('/all')
@API.param('start', 'Zero-based page offset. Default ``1``.', type='integer')
@API.param('limit', 'Page size, max items returned per call. Default ``100``,'
                    f' max ``{MAX_PAGE_LIMIT}``.',
           type='integer')
class HostDetailListApi(Resource):
    """Paginated listing of every host."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'A page of host objects plus pagination links.',
                  LIST_RESPONSE)
    @API.response(400, 'Pagination params not numeric, negative, or limit '
                       f'above {MAX_PAGE_LIMIT}.', ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """List every host (objects excluded), with cursor-style pagination.

        The response carries ``_links.next`` / ``_links.prev`` URLs you
        can follow until ``next`` is absent.
        """
        results = []
        try:
            start = int(request.args.get('start', 1))
            limit = int(request.args.get('limit', 100))
        except (TypeError, ValueError):
            abort(400, "start and limit must be integers")
        if start < 0 or limit < 0:
            abort(400, "start and limit must be non-negative")
        if limit > MAX_PAGE_LIMIT:
            abort(400, f"limit must be <= {MAX_PAGE_LIMIT}")
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
