"""
API
"""
from functools import wraps
from flask import abort, request
from application.models.account import Account

def require_token(fn): #pylint: disable=invalid-name
    """
    Decorator for Endpoints with token
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        login_header = request.headers.get('x-login-header')
        if not login_header:
            abort(401, "Invalid Request, x-login-header missing")

        try:
            login_user, login_password = login_header.split(':')
            if Account.objects.get(username=login_user, type="restapi").get_password() != login_password:
                raise ValueError("Invalid Login")
        except: #pylint: disable=bare-except
            abort(401, "Invalid login Token")

        return fn(*args, **kwargs)

    return decorated_view
