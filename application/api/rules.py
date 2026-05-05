"""
Rules API.

Read and write syncer configuration over HTTP. Builds on the same
``rule_import_export`` helpers used by ``cmdbsyncer rules import_rules``
/ ``export_rules`` and the autorules cronjob, so CLI and API stay in
lockstep.

Auth: ``@require_token``. A user with ``api_roles = ['rules']`` (or
``'all'``) can call this namespace.
"""
import json

from flask import request
from flask_restx import Namespace, Resource, fields

from application import log
from application.api import require_token
from application.plugins.rules.rule_definitions import rules as enabled_rules
from application.plugins.rules.rule_import_export import (
    iter_rules_of_type,
    import_one_rule,
    import_rule_lines,
    import_json_bundle,
    grouped_rules_export,
)
from application.plugins.rules.autorules import create_rules


API = Namespace(
    'rules',
    description=(
        "Read and write syncer rule configuration. Shares the import / "
        "export / autorules helpers with the ``cmdbsyncer rules`` CLI "
        "and the autorules cronjob, so all three stay in lockstep. A "
        "user with ``api_roles = ['rules']`` (or ``'all'``) can call "
        "this namespace."
    ),
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

ERROR = API.model('error', {
    'message': fields.String(description='Human-readable error message'),
})

RULE_TYPES_RESPONSE = API.model('rule_types_response', {
    'rule_types': fields.List(fields.String,
                              description='Sorted list of every supported '
                                          'rule_type ident.'),
})

RULES_BY_TYPE_RESPONSE = API.model('rules_by_type_response', {
    'rule_type': fields.String,
    'rules': fields.List(fields.Raw,
                         description='Each item is a single rule serialised '
                                     'via ``Document.to_json()``. Round-trips '
                                     'unchanged through ``POST``.'),
})

RULE_IMPORT_REQUEST = API.model('rule_import_request', {
    'rule_type': fields.String(required=False,
                               description='Default rule_type for items that '
                                           'do not carry a header line.'),
    'rules': fields.Raw(description='Either a list of rule dicts (single '
                                    'type), or an object keyed by rule_type '
                                    'with a list of dicts as value '
                                    '(multi-type, same shape as '
                                    '``GET /rules/export``).',
                        required=True),
})

RULE_IMPORT_RESPONSE = API.model('rule_import_response', {
    'imported': fields.Raw(description='Imported counts keyed by rule_type.'),
    'total': fields.Integer(description='Sum of imported counts.'),
})

RULE_BY_TYPE_POST_RESPONSE = API.model('rule_by_type_post_response', {
    'rule_type': fields.String,
    'imported': fields.Integer,
    'duplicate': fields.Integer(description='Items skipped because a rule '
                                            'with the same id already exists.'),
    'invalid': fields.Integer(description='Items rejected by Mongo schema '
                                          'validation.'),
})

RULES_EXPORT_RESPONSE = API.model('rules_export_response', {
    'exported_at': fields.String(example='2026-04-26T17:55:00Z',
                                 description='ISO-8601 UTC timestamp.'),
    'rules': fields.Raw(description='Object keyed by rule_type, each value '
                                    'is a list of rule dicts.'),
})

AUTORULES_REQUEST = API.model('autorules_request', {
    'debug': fields.Boolean(default=False,
                            description='Run the autorules pass with debug '
                                        'logging enabled.'),
})

AUTORULES_RESPONSE = API.model('autorules_response', {
    'status': fields.String(example='ok'),
})


def _decode_rule_lines(rules):
    """Yield JSON dicts from ``to_json()`` strings.

    Skipped lines are surfaced in the syncer Log so a corrupted rule
    document doesn't silently disappear from /rules/<type> exports.
    """
    for raw in rules:
        try:
            yield json.loads(raw)
        except (ValueError, TypeError) as exp:
            preview = (raw[:200] + '…') if isinstance(raw, str) and len(raw) > 200 else raw
            log.log(
                f"Skipping rule with invalid JSON: {exp}",
                source='api.rules',
                details=[('error', str(exp)), ('preview', str(preview))],
            )
            continue


@API.route('/types')
class RuleTypes(Resource):
    """Discoverable list of supported rule types."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Sorted list of rule_type idents.', RULE_TYPES_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """Return every rule_type ident the server knows about."""
        return {'rule_types': sorted(enabled_rules)}


@API.route('/<string:rule_type>')
@API.param('rule_type',
           'Rule type ident — call ``GET /rules/types`` for the catalog.')
class RulesByType(Resource):
    """Read or create rules of one type."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(200, 'Every rule of this type as a JSON list.',
                  RULES_BY_TYPE_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'Unknown rule_type.', ERROR)
    @require_token
    def get(self, rule_type):
        """Export every rule of *rule_type* as a JSON list."""
        if rule_type not in enabled_rules:
            return {'message': f"Unknown rule_type '{rule_type}'"}, 404
        return {
            'rule_type': rule_type,
            'rules': list(_decode_rule_lines(iter_rules_of_type(rule_type))),
        }

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.response(201, 'At least one rule was newly persisted.',
                  RULE_BY_TYPE_POST_RESPONSE)
    @API.response(200, 'Body parsed but every item was a duplicate '
                       'or invalid — nothing new was saved.',
                  RULE_BY_TYPE_POST_RESPONSE)
    @API.response(400, 'Body was not JSON.', ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @API.response(404, 'Unknown rule_type.', ERROR)
    @require_token
    def post(self, rule_type):
        """Create one or many rules of *rule_type*.

        Body may be either a single rule dict or a list of dicts; the
        document layout is the same as the export form (one ``to_json()``
        per rule).
        """
        if rule_type not in enabled_rules:
            return {'message': f"Unknown rule_type '{rule_type}'"}, 404
        payload = request.get_json(silent=True)
        if payload is None:
            return {'message': 'Request body must be JSON'}, 400
        items = payload if isinstance(payload, list) else [payload]

        results = {'imported': 0, 'duplicate': 0, 'invalid': 0}
        for item in items:
            if not isinstance(item, dict):
                results['invalid'] += 1
                continue
            status = import_one_rule(item, rule_type)
            if status == 'unknown_type':
                # ``rule_type`` was already validated above, so this only
                # fires if the model module disappeared mid-request.
                return {'message': f"Model for '{rule_type}' not loadable"}, 500
            results[status] = results.get(status, 0) + 1
        status_code = 201 if results['imported'] else 200
        return {'rule_type': rule_type, **results}, status_code


@API.route('/export')
class RulesExport(Resource):
    """Bulk export of every known rule type."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.param('include_hosts',
               'Set to ``1`` to also export the ``host_objects`` collection. '
               'Skipped by default — usually not what you want in a rule '
               'backup.')
    @API.param('include_accounts',
               'Set to ``1`` to also export accounts. Skipped by default.')
    @API.param('include_users',
               'Set to ``1`` to also export users. The output contains hashed '
               'passwords and role assignments — treat as secret. Skipped by '
               'default.')
    @API.response(200, 'Every rule, grouped by ``rule_type``.',
                  RULES_EXPORT_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def get(self):
        """Return every enabled rule type, grouped by type."""
        def _flag(name):
            return request.args.get(name, '').lower() in ('1', 'true', 'yes')
        return grouped_rules_export(
            include_hosts=_flag('include_hosts'),
            include_accounts=_flag('include_accounts'),
            include_users=_flag('include_users'),
        )


@API.route('/import')
class RulesImport(Resource):
    """Bulk import that matches the on-disk JSONL format."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(RULE_IMPORT_REQUEST, validate=False)
    @API.response(200, 'Imported counts keyed by rule_type, plus the total.',
                  RULE_IMPORT_RESPONSE)
    @API.response(400, 'JSON body could not be parsed.', ERROR)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def post(self):
        """Import rules.

        Accepts one of:

        * ``{"rule_type": "...", "rules": [<dict>, ...]}`` — explicit
          single-type payload.
        * ``{"rules": {"<rule_type>": [<dict>, ...], ...}}`` — multi-type
          payload, the same shape returned by ``GET /rules/export``.
        * Plain text body in the on-disk JSONL form (``Content-Type:
          text/plain``), with optional ``{"rule_type": "..."}`` header
          lines.
        """
        ctype = (request.content_type or '').split(';', 1)[0].strip().lower()
        if ctype == 'application/json':
            payload = request.get_json(silent=True)
            if payload is None:
                return {'message': 'Body must be JSON'}, 400
            counts = import_json_bundle(payload)
        else:
            body = request.get_data(as_text=True) or ''
            counts = import_rule_lines(body.splitlines())
        return {'imported': counts, 'total': sum(counts.values())}


@API.route('/autorules')
class Autorules(Resource):
    """Trigger the rule-automation pass that builds rules from host data."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @API.expect(AUTORULES_REQUEST, validate=False)
    @API.response(200, 'Autorules run completed successfully.',
                  AUTORULES_RESPONSE)
    @API.response(401, 'Authentication failed', ERROR)
    @require_token
    def post(self):
        """Run the autorules creator. Body is optional; pass
        ``{"debug": true}`` for verbose output in the server log."""
        payload = request.get_json(silent=True) or {}
        debug = bool(payload.get('debug'))
        create_rules(account=False, debug=debug)
        return {'status': 'ok'}, 200
