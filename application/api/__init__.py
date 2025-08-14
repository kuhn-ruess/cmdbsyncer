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
        login_account = request.headers.get('x-login-account')
        if not login_header and not login_account:
            abort(401, f"Invalid Request, Loginheader missing ({login_header}, {login_account})")
        try:
            if login_header:
                login_user, login_password = login_header.split(':', 1)
                account_obj = Account.objects.get(username=login_user, type="restapi")
            if login_account:
                login_account_name, login_password = login_account.split(':', 1)
                account_obj = Account.objects.get(name=login_account_name, type="restapi")
            if account_obj.get_password() != login_password:
                raise ValueError("Invalid Login Account Name")
        except: #pylint: disable=bare-except
            abort(401, "Invalid login Token")

        return fn(*args, **kwargs)

    return decorated_view
