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
        login_token = request.headers.get('x-login-token')
        if not login_token:
            abort(401, "Invalid Request, x-login-token missing")

        try:
            Account.objects.get(typ='restapi', password=login_token, enabled=True)
        except: #pylint: disable=bare-except
            abort(401, "Invalid login Token")

        return fn(*args, **kwargs)

    return decorated_view
