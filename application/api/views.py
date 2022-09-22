"""
API Endpoints
"""
from functools import wraps
from flask import Blueprint
from flask_restx import Api

from application import app
from application.api.ansible import API as ansible

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
                        "Origin, x-access-token, Content-Type, Accept"
    return response


AUTHORIZATIONS = {
    'x-login-token': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'x-login-token'
    }
}

PARAMS = {
}

SWAGGER_ENABLED = app.config.get("SWAGGER_ENABLED")
if not SWAGGER_ENABLED:
    PARAMS['doc'] = False

# x-login-token includes consumer_id as 'sub'
API = Api(API_BP, authorizations=AUTHORIZATIONS, security=['x-login-token'], **PARAMS)

API.add_namespace(ansible, path='/ansible')
