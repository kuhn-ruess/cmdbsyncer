"""
API Endpoints
"""
from flask import Blueprint
from flask_restx import Api

from application import app, limiter
from application.api.syncer import API as syncer
from application.api.objects import API as objects
from application.api.rules import API as rules
from application.api.inventory import API as ansible

API_BP = Blueprint('api', __name__)

# Rate-limit API auth failures per client IP. Only 401 responses deduct from
# the bucket, so legitimate high-volume API traffic is not throttled — only
# brute-force / credential-stuffing attempts are.
limiter.limit(
    lambda: app.config.get('AUTH_RATE_LIMIT', '3 per minute; 10 per hour'),
    deduct_when=lambda response: response.status_code == 401,
)(API_BP)

@API_BP.errorhandler(401)
def custom401(error):
    """ Custom 401 API Response """
    return {'status' : 401, 'message' : error}, 401


AUTHORIZATIONS = {
    'x-login-user': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'x-login-user',
        'description': 'Token fallback. Prefer HTTPS with Authorization: Basic'
    },
    'basicAuth' : {
        'type': 'basic',
        'description': 'Preferred API authentication over HTTPS'
    }
}

PARAMS = {
}

SWAGGER_ENABLED = app.config.get("SWAGGER_ENABLED")
if not SWAGGER_ENABLED:
    PARAMS['doc'] = False

API = Api(API_BP, authorizations=AUTHORIZATIONS,
          security=['x-login-user', 'basicAuth'], **PARAMS)


API.add_namespace(syncer, path='/syncer')
API.add_namespace(objects, path='/objects')
API.add_namespace(rules, path='/rules')
API.add_namespace(ansible, path='/ansible')
