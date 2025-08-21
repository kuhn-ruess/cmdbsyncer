"""
API
"""
from functools import wraps
from flask import abort, request
from application.models.account import Account
from application.models.user import User
from mongoengine.errors import DoesNotExist

def require_token(fn): #pylint: disable=invalid-name
    """
    Decorator for Endpoints with token
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        if login_user := request.headers.get('x-login-user'):
            username, user_password = login_user.split(':', 1)
            try:
                user_result = User.objects.get(
                    disabled__ne=True,
                    __raw__={'$or': [{'name': username}, {'email': username}]}
                )
            except DoesNotExist:
                abort(401, "Invalid login")
            if not user_result.check_password(user_password):
                abort(401, "Invalid login")
        elif request.headers.get('x-login-token'):
            abort(
                401,
                "Please Migrate to x-login-user authentication. "
                "Due to security reasons, this login is no longer possible"
            )
        else:
            abort(401, "Invalid Request, Loginheader missing")

        return fn(*args, **kwargs)

    return decorated_view
