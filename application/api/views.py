"""
API Endpoints
"""
from flask import Blueprint
from flask_restx import Api

from application import app
from application.api.syncer import API as syncer
from application.api.objects import API as objects

API_BP = Blueprint('api', __name__)

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
