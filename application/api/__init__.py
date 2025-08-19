"""
API
"""
from functools import wraps
from flask import abort, request
from application.models.account import Account
from application.models.user import User

def require_token(fn): #pylint: disable=invalid-name
    """
    Decorator for Endpoints with token
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        try:
            if login_user := request.headers.get('x-login-user'):
                username, user_password = login_user.split(':', 1)
                user_result = User.objects.get(email=username, disabled__ne=True)
                if not user_result.check_password(user_password):
                    raise ValueError("Invalid Login")
            else:
                abort(401, "Invalid Request, Loginheader missing")
        except: #pylint: disable=bare-except
            abort(401, "Invalid login")

        return fn(*args, **kwargs)

    return decorated_view
