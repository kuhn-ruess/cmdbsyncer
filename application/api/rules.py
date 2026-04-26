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
from datetime import datetime

from flask import request
from flask_restx import Namespace, Resource

from application.api import require_token
from application.plugins.rules.rule_definitions import rules as enabled_rules
from application.plugins.rules.rule_import_export import (
    iter_rules_of_type,
    iter_all_rules,
    import_one_rule,
    import_rule_lines,
)
from application.plugins.rules.autorules import create_rules


API = Namespace('rules', description='Read and write syncer rule configuration')


def _decode_rule_lines(rules):
    """Yield JSON dicts from ``to_json()`` strings."""
    for raw in rules:
        try:
            yield json.loads(raw)
        except (ValueError, TypeError):
            continue


@API.route('/types')
class RuleTypes(Resource):
    """Discoverable list of supported rule types."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @require_token
    def get(self):
        """Return the supported rule_type idents."""
        return {'rule_types': sorted(enabled_rules)}


@API.route('/<string:rule_type>')
@API.param('rule_type', 'Rule type ident — see GET /rules/types')
class RulesByType(Resource):
    """Read or create rules of one type."""

    @API.doc(security=['x-login-user', 'basicAuth'])
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
    @API.param('include_hosts', 'Set to 1 to also export the host_objects '
                                'collection (skipped by default).')
    @API.param('include_accounts', 'Set to 1 to also export accounts '
                                   '(skipped by default).')
    @API.param('include_users', 'Set to 1 to also export users — output '
                                'contains hashed passwords (skipped by default).')
    @require_token
    def get(self):
        """Return every enabled rule type, grouped by type."""
        def _flag(name):
            return request.args.get(name, '').lower() in ('1', 'true', 'yes')
        grouped = {}
        for rule_type, rule in iter_all_rules(
            include_hosts=_flag('include_hosts'),
            include_accounts=_flag('include_accounts'),
            include_users=_flag('include_users'),
        ):
            try:
                grouped.setdefault(rule_type, []).append(json.loads(rule))
            except (ValueError, TypeError):
                continue
        return {
            'exported_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'rules': grouped,
        }


@API.route('/import')
class RulesImport(Resource):
    """Bulk import that matches the on-disk JSONL format."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @require_token
    def post(self):
        """Import rules.

        Accepts one of:

        * ``{"rule_type": "...", "rules": [<dict>, ...]}`` — explicit
          single-type payload.
        * ``{"rules": {"<rule_type>": [<dict>, ...], ...}}`` — multi-type
          payload, the same shape returned by ``GET /rules/export``.
        * Plain text body in the on-disk JSONL form, with optional
          ``{"rule_type": "..."}`` header lines.
        """
        ctype = (request.content_type or '').split(';', 1)[0].strip().lower()
        if ctype == 'application/json':
            payload = request.get_json(silent=True)
            if payload is None:
                return {'message': 'Body must be JSON'}, 400
            counts = _import_json_payload(payload)
        else:
            body = request.get_data(as_text=True) or ''
            counts = import_rule_lines(body.splitlines())
        return {'imported': counts, 'total': sum(counts.values())}


def _import_json_payload(payload):
    """Dispatch the two supported JSON shapes onto ``import_rule_lines``."""
    if isinstance(payload, dict) and 'rules' in payload:
        rules = payload['rules']
        if isinstance(rules, list):
            # Single-type form
            rule_type = payload.get('rule_type')
            return import_rule_lines(rules, default_rule_type=rule_type)
        if isinstance(rules, dict):
            # Multi-type form: replay as header + body lines.
            counts = {}
            for rule_type, items in rules.items():
                if not isinstance(items, list):
                    continue
                sub = import_rule_lines(items, default_rule_type=rule_type)
                for k, v in sub.items():
                    counts[k] = counts.get(k, 0) + v
            return counts
    return {}


@API.route('/autorules')
class Autorules(Resource):
    """Trigger the rule-automation pass that builds rules from host data."""

    @API.doc(security=['x-login-user', 'basicAuth'])
    @require_token
    def post(self):
        """Run the autorules creator. Optional body ``{"debug": true}``."""
        payload = request.get_json(silent=True) or {}
        debug = bool(payload.get('debug'))
        create_rules(account=False, debug=debug)
        return {'status': 'ok'}, 200
