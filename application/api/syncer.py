"""
Syncer API.

Read-only access to log entries, cron status, host counters, plus a
webhook trigger for cron groups. Authenticated via ``@require_token``;
a user with ``api_roles = ['syncer']`` (or ``'all'``) can call this
namespace. The ``/cron/trigger/<group>`` route additionally accepts an
``X-Webhook-Token`` header tied to the CronGroup, so external systems
can fire a sync without carrying a user credential.
"""
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

API = Namespace(
    'syncer',
    description='Logs, cron status, host counters and webhook triggers.',
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

LOG_DETAIL = API.model('log_detail', {
    'name': fields.String(description='Severity / level label'),
    'message': fields.String(description='Detail line text'),
})

LOG_ENTRY = API.model('log_entry', {
    'entry_id': fields.String(description='Mongo ObjectId of the log entry'),
    'time': fields.String(example='2026-04-26 17:55:00',
                          description='Local time the entry was written'),
    'message': fields.String(description='Top-line summary'),
    'source': fields.String(description='Source / component name '
                                       '(e.g. "API", "checkmk")'),
    'details': fields.List(fields.Nested(LOG_DETAIL),
                           description='Per-line detail rows'),
    'has_error': fields.Boolean(description='True iff at least one detail '
                                            'line is at error level'),
})

LOG_RESPONSE = API.model('log_response', {
    'result': fields.List(fields.Nested(LOG_ENTRY)),
})

LOG_SINGLE_RESPONSE = API.model('log_single_response', {
    'result': fields.Nested(LOG_ENTRY),
})

CRON_STATUS = API.model('cron_status', {
    'name': fields.String(description='Cron group name'),
    'last_start': fields.String(example='2026-04-26 17:50:00',
                                description='Last execution time, '
                                            'or null if never ran'),
    'next_run': fields.String(example='2026-04-26 18:00:00',
                              description='Scheduled next run, or null'),
    'is_running': fields.Boolean(description='True while a run is in flight'),
    'last_message': fields.String(description='Last progress / result line'),
    'has_error': fields.Boolean(description='True iff the last run failed'),
})

CRON_LIST_RESPONSE = API.model('cron_list_response', {
    'result': fields.List(fields.Nested(CRON_STATUS)),
})

CRON_UPDATE = API.model('cron_update', {
    'job_name': fields.String(required=True,
                              description='Name of the CronGroup to update'),
    'run_once_next': fields.Boolean(required=True,
                                    description='Set true to schedule one '
                                                'extra run on the next pass'),
})

CRON_TRIGGER_RESPONSE = API.model('cron_trigger_response', {
    'status': fields.String(example='triggered'),
    'group': fields.String(description='Group name that was scheduled'),
    'note': fields.String(description='Human-readable scheduling hint'),
})

HOSTS_STATS = API.model('hosts_stats', {
    '24h_checkpoint': fields.String(example='2026-04-25 17:55:00',
                                    description='Cut-off used by '
                                                '``not_updated_last_24h``'),
    'num_hosts': fields.Integer(description='Total hosts in the syncer'),
    'num_objects': fields.Integer(description='Total non-host objects '
                                              '(e.g. apps, services)'),
    'not_updated_last_24h': fields.Integer(
        description='Hosts whose ``last_import_seen`` is older than 24h'),
})

ERROR = API.model('error', {
    'error': fields.String(description='Human-readable error message'),
})

STATUS = API.model('status', {
    'status': fields.String(example='saved'),
})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@API.route('/logs')
class SyncerLogsApi(Resource):
    """Latest entries from the syncer log."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Last 100 log entries, newest first.', LOG_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """Return the latest 100 log messages, newest first."""
        limit = 100
        response = []
        for entry in LogEntry.objects().order_by('-id')[:limit]:
            response.append({
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [{'name': x.level, 'message': x.message}
                            for x in entry.details],
                'has_error': entry.has_error,
            })
        return {
            'result': response,
        }, 200


@API.route('/services/<service_name>')
@API.param('service_name', 'Component / source ident as written to '
                           'log entries (e.g. ``checkmk``, ``netbox``).')
class SyncerServiceApi(Resource):
    """Most recent log entry for a single source component."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Latest log entry for the source.', LOG_SINGLE_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'No log entry exists for this service yet.', ERROR)
    @require_token
    def get(self, service_name):
        """Return the most recent log message for the given service."""
        try:
            entry = LogEntry.objects(source=service_name).order_by('-id').first()
            if not entry:
                raise IndexError
            response = {
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [{'name': x.level, 'message': x.message}
                            for x in entry.details],
                'has_error': entry.has_error,
            }
            return {
                'result': response,
            }, 200
        except IndexError:
            return {
                'error': "No Entry for Service Found",
            }, 404


@API.route('/cron/')
class SyncerCronApi(Resource):
    """Status of every CronGroup, plus the run-once-next trigger."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Status for every CronGroup.', CRON_LIST_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """Return the current status of every CronGroup."""
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

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(CRON_UPDATE, validate=True)
    @API.response(200, 'Cron group updated.', STATUS)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'CronGroup with that name does not exist.', ERROR)
    @require_token
    def post(self):
        """Mark a CronGroup to run once on the next cron pass.

        Set ``run_once_next: true`` to schedule one extra run outside the
        group's usual interval; ``false`` clears the flag.
        """
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
@API.param('group_name', 'CronGroup name to trigger.')
class SyncerCronTriggerApi(Resource):
    """
    Webhook trigger that schedules a CronGroup to run on the next cron
    pass. Authentication can be:

    * standard user auth (Basic / x-login-user), checked against the
      caller's ``api_roles``;
    * an enterprise webhook signature policy, when configured;
    * a per-group ``X-Webhook-Token`` header, set on the CronGroup.

    External systems (GitHub, Jenkins, Netbox hooks, …) typically use
    the third option so they can fire a sync without carrying a user
    credential.
    """

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.doc(params={'X-Webhook-Token': {
        'in': 'header',
        'description': ('Per-CronGroup webhook token. When set on the '
                        'CronGroup, callers may use this header instead of '
                        'user credentials.'),
        'required': False,
    }})
    @API.response(202, 'Run scheduled for the next cron pass.',
                  CRON_TRIGGER_RESPONSE)
    @API.response(401, 'Token mismatch or no valid credentials.', ERROR)
    @API.response(403, 'Webhook is disabled for this CronGroup.', ERROR)
    @API.response(404, 'CronGroup with that name does not exist.', ERROR)
    @API.response(409, 'CronGroup is disabled and cannot run.', ERROR)
    def post(self, group_name):
        """Schedule a one-off run of the named CronGroup."""
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
            # Hash-on-read: legacy rows still carrying plaintext get
            # upgraded the first time they authenticate after the
            # rollout, so operators don't have to run a separate
            # migration step.
            if group.migrate_legacy_webhook_token():
                group.save()
            if not group.webhook_enabled or not group.webhook_token_hash:
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
            # verify_webhook_token uses hmac.compare_digest internally.
            if not group.verify_webhook_token(token):
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
    """Aggregate counters over the host collection."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Aggregate host stats.', HOSTS_STATS)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """Return totals plus a 24-hour staleness counter."""
        ago_24h = datetime.now() - timedelta(hours=24)
        return {
            '24h_checkpoint': str(ago_24h),
            'num_hosts': Host.objects(is_object=False).count(),
            'num_objects': Host.objects(is_object=True).count(),
            'not_updated_last_24h': Host.objects(
                is_object=False,
                last_import_seen__lt=ago_24h,
            ).count(),
        }, 200
