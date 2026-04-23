"""
Ansible Api
"""
import hmac
from datetime import datetime, timedelta
from mongoengine.errors import DoesNotExist
from flask import request
from flask_restx import Namespace, Resource, fields

from application import log
from application.api import require_token
from application.enterprise import run_hook as _ent_run_hook
from application.helpers.audit import audit
from application.modules.log.models import LogEntry
from application.models.host import Host
from application.models.cron import CronStats, CronGroup

API = Namespace('syncer')


@API.route('/logs')
class SyncerLogsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Return latest 100 Log Messages"""
        limit = 100
        response = []
        for entry in LogEntry.objects().order_by('-id')[:limit]:
            response.append({
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [ {'name': x.level, 'message': x.message} for x in entry.details],
                'has_error': entry.has_error,
            })
        return {
            'result': response,
        }, 200

@API.route('/services/<service_name>')
class SyncerServiceApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self, service_name):
        """Return latest Message of given Service"""
        try:
            entry = LogEntry.objects(source=service_name).order_by('-id').first()
            if not entry:
                raise IndexError
            response = {
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [ {'name': x.level, 'message': x.message} for x in entry.details],
                'has_error': entry.has_error,
            }
            return {
                'result': response,
            }, 200
        except IndexError:
            return {
                'error': "No Entry for Service Found",
            }, 404

CRON_MODEL = API.model(
    'cron_update',
    {
        'job_name': fields.String(required=True),
        'run_once_next': fields.Boolean(required=True),
    },
)

@API.route('/cron/')
class SyncerCronApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Return Status of Cronjob Groups"""
        try:
            response = []
            for entry in CronStats.objects:
                last_start = entry.last_start
                if last_start:
                    last_start = last_start.strftime('%Y-%m-%d %H:%M:%S')
                next_run = entry.next_run
                if next_run:
                    next_run = next_run.strftime('%Y-%m-%d %H:%M:%S')
                response.append({
                    'name': str(entry.group),
                    'last_start': last_start,
                    'next_run': next_run,
                    'is_running': entry.is_running,
                    'last_message': entry.last_message,
                    'has_error': entry.failure,
                })
            return {
                'result': response,
            }, 200
        except DoesNotExist:
            return {
                'error': "No Status for CronGroup Found",
            }, 404

    @require_token
    @API.expect(CRON_MODEL, validate=True)
    def post(self):
        """ Update Cronjob """
        try:
            req_json = request.json
            job_name = req_json['job_name']
            run_once_next = req_json['run_once_next']
            job = CronGroup.objects.get(name=job_name)
            job.run_once_next = run_once_next
            job.save()
            status = 'saved'
            status_code = 200

            return {'status': status}, status_code
        except DoesNotExist:
            return {
                'error': "Cron not Found",
            }, 404




@API.route('/cron/trigger/<string:group_name>')
class SyncerCronTriggerApi(Resource):
    """
    Webhook trigger: marks a CronGroup as run-once-next so the next cron
    pass runs it outside its normal schedule. Accepts either standard user
    auth (matching the existing API role rules) or a per-group
    `X-Webhook-Token` header, so external systems (GitHub, Jenkins,
    Netbox hooks, …) can fire a sync without carrying a user credential.
    """

    def post(self, group_name):
        """Trigger a cron group run"""
        try:
            group = CronGroup.objects.get(name=group_name)
        except DoesNotExist:
            return {'error': "Cron not Found"}, 404

        # Enterprise webhook_signatures: when a signature policy is attached
        # to this group, the enterprise verifier runs first. It returns:
        #   'ok'   → validation passed, skip the OSS auth below
        #   dict   → validation failed, propagate status/error verbatim
        #   None   → no policy / not licensed, fall through to OSS auth
        enterprise_result = _ent_run_hook('webhook_auth', group, request)
        auth_method = None
        if enterprise_result == 'ok':
            auth_method = 'signature'
        elif isinstance(enterprise_result, dict):
            reason = enterprise_result.get('error', 'Unauthorized')
            status = enterprise_result.get('status', 401)
            log.log("Webhook trigger rejected", source="API",
                    details=[('group', group_name),
                             ('reason', reason),
                             ('ip', request.remote_addr)])
            audit('webhook.rejected', outcome='failure',
                  actor_type='webhook',
                  target_type='CronGroup', target_id=str(group.id),
                  target_name=group_name,
                  metadata={'reason': reason})
            return {'error': reason}, status

        token = request.headers.get('X-Webhook-Token')
        if auth_method is None and token:
            if not group.webhook_enabled or not group.webhook_token:
                log.log("Webhook trigger rejected", source="API",
                        details=[('group', group_name),
                                 ('reason', 'webhook disabled or no token set'),
                                 ('ip', request.remote_addr)])
                audit('webhook.rejected', outcome='failure',
                      actor_type='webhook',
                      target_type='CronGroup', target_id=str(group.id),
                      target_name=group_name,
                      metadata={'reason': 'webhook disabled or no token set'})
                return {'error': "Webhook not enabled for this group"}, 403
            # hmac.compare_digest prevents timing-based token discovery.
            if not hmac.compare_digest(token, group.webhook_token):
                log.log("Webhook trigger rejected", source="API",
                        details=[('group', group_name),
                                 ('reason', 'token mismatch'),
                                 ('ip', request.remote_addr)])
                audit('webhook.rejected', outcome='failure',
                      actor_type='webhook',
                      target_type='CronGroup', target_id=str(group.id),
                      target_name=group_name,
                      metadata={'reason': 'token mismatch'})
                return {'error': "Invalid webhook token"}, 401
            auth_method = 'token'
        elif auth_method is None:
            # No enterprise signature and no webhook token → fall back to
            # normal user auth. Calling the decorator with a no-op lets
            # us reuse the existing credential, HTTPS and role-path checks,
            # which abort(401) on failure so control only returns here
            # when the caller is valid.
            require_token(lambda: None)()
            auth_method = 'user'

        if not group.enabled:
            return {'error': "Group disabled"}, 409

        group.run_once_next = True
        group.save()
        log.log("Cron group triggered via webhook", source="API",
                details=[('group', group_name),
                         ('auth', auth_method),
                         ('ip', request.remote_addr)])
        audit('webhook.triggered',
              actor_type='user' if auth_method == 'user' else 'webhook',
              target_type='CronGroup', target_id=str(group.id),
              target_name=group_name,
              metadata={'auth': auth_method})
        return {
            'status': 'triggered',
            'group': group_name,
            'note': 'Group will run on the next cron pass.',
        }, 202


@API.route('/hosts')
class SyncerHostsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Get Status of Imported Hosts"""
        ago_24h = datetime.now() - timedelta(hours=24)
        return {
            '24h_checkpoint' : str(ago_24h),
            'num_hosts': Host.objects(is_object=False).count(),
            'num_objects': Host.objects(is_object=True).count(),
            'not_updated_last_24h': Host.objects(is_object=False,
                                                 last_import_seen__lt=ago_24h).count(),
        }, 200
