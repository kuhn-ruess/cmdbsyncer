"""
Notification Hub REST API.

Mounted under `/api/v1/notify/` from the plugin __init__ via the
shared `syncerapi.v1.rest.API` namespace registry — same pattern the
Ansible/SNOW/Checkmk plugins use. That way the endpoint appears in
Swagger, is CSRF-exempt (the whole `api` blueprint is), and the
per-IP rate limit applies automatically.

Endpoints:

  POST /api/v1/notify/dispatch
      Accept an event, persist it as a NotifyDispatchJob, return
      202 with the job ID. A background worker picks it up, runs
      the rule evaluator and writes the outcome back.

  GET  /api/v1/notify/dispatch/<job_id>
      Status + per-recipient outcomes of a previously submitted
      job. Handy for callers that want to poll after enqueueing.
"""
from flask import request
from flask_restx import Namespace, Resource, fields

from application.api import require_token
from application.plugins.notify.queue import (
    enqueue as _enqueue_job,
    get_job as _get_job,
)


API = Namespace(
    'notify',
    description="Notification Hub — dispatch incoming events through "
                "the contact/group/rule engine and deliver them via "
                "the configured channels.",
)


_EVENT = API.model('NotifyEvent', {
    'source':     fields.String(
        example='checkmk',
        description="Event source identifier (matched by DispatchRule)."),
    'event_type': fields.String(
        required=True, example='host.down',
        description="Event type, regex-matched by DispatchRule."),
    'host':       fields.String(example='web01.example.com'),
    'service':    fields.String(example='CPU Load'),
    'state':      fields.String(example='CRIT'),
    'title':      fields.String(example='[CRIT] web01 host down'),
    'message':    fields.String(example='PING CRITICAL - 100% packet loss'),
    'context':    fields.Raw(
        description="Arbitrary key/value map forwarded to the "
                    "resolver for context-key matchers (e.g. the "
                    "Checkmk $CONTACTGROUPS$ macro)."),
})

_ACCEPTED = API.model('NotifyAccepted', {
    'accepted': fields.Boolean(example=True),
    'job_id':   fields.String(example='65a9…'),
    'status':   fields.String(example='queued'),
})

_OUTCOME = API.model('NotifyOutcome', {
    'contact': fields.String(),
    'channel': fields.String(),
    'outcome': fields.String(example='ok'),
    'error':   fields.String(),
})

_JOB = API.model('NotifyJob', {
    'id':          fields.String(),
    'status':      fields.String(example='done'),
    'source':      fields.String(),
    'event_type':  fields.String(),
    'host':        fields.String(),
    'service':     fields.String(),
    'state':       fields.String(),
    'received_at': fields.DateTime(),
    'started_at':  fields.DateTime(),
    'finished_at': fields.DateTime(),
    'attempts':    fields.Integer(),
    'error':       fields.String(),
    'outcomes':    fields.List(fields.Nested(_OUTCOME)),
})


@API.route('/dispatch')
class NotifyDispatchApi(Resource):
    """Accept an inbound event and enqueue it for dispatch."""

    @require_token
    @API.expect(_EVENT, validate=False)
    @API.marshal_with(_ACCEPTED, code=202)
    def post(self):
        """Enqueue an event. Returns immediately with the job id."""
        event = request.get_json(silent=True) or {}
        if not event.get('event_type'):
            API.abort(400, "event_type is required")
        try:
            job = _enqueue_job(event)
        except RuntimeError as exp:
            API.abort(503, str(exp))
        return {
            'accepted': True,
            'job_id':   job['id'],
            'status':   job['status'],
        }, 202


@API.route('/dispatch/<string:job_id>')
class NotifyDispatchJobApi(Resource):
    """Read back the status + outcomes of a previously submitted job."""

    @require_token
    @API.marshal_with(_JOB)
    def get(self, job_id):
        """Return the full job record from the RAM queue."""
        job = _get_job(job_id)
        if job is None:
            API.abort(404, "Job not found or evicted from history")
        return job
