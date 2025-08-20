"""
API Endpoints
"""
from flask import Blueprint
from flask_restx import Api

from application import app
from application.api.ansible import API as ansible
from application.api.syncer import API as syncer
from application.api.objects import API as objects

API_BP = Blueprint('api', __name__)

@API_BP.errorhandler(401)
def custom401(error):
    """ Custom 401 API Response """
    return {'status' : 401, 'message' : error}, 401

@API_BP.after_request
def apply_headers(response):
    """ Additional Headers """
    if app.config.get('APPLY_HEADERS'):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"

    response.headers["Access-Control-Allow-Headers"] =\
                        "Origin, x-login-user, x-login-token, Content-Type, Accept"
    return response


AUTHORIZATIONS = {
    'x-login-user': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'x-login-user',
        'description': 'Needs to be user_name:password'
    },
    'x-login-token': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'x-login-token',
        'description': 'Deprecated, please change to x-login-user'
    },
}

PARAMS = {
}

SWAGGER_ENABLED = app.config.get("SWAGGER_ENABLED")
if not SWAGGER_ENABLED:
    PARAMS['doc'] = False

API = Api(API_BP, authorizations=AUTHORIZATIONS, security=['x-login-user', 'x-login-token'], **PARAMS)


API.add_namespace(ansible, path='/ansible')
API.add_namespace(syncer, path='/syncer')
API.add_namespace(objects, path='/objects')
