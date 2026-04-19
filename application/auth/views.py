"""
Login Routes
"""
from datetime import datetime
from datetime import timedelta
import pyotp
from flask import request, render_template, current_app, \
     flash, redirect, session, Blueprint, url_for
from flask_login import current_user, login_user, logout_user, login_required
from authlib.jose import jwt, JoseError
from mongoengine.errors import DoesNotExist

from application import login_manager, app, log, limiter
from application.enterprise import run_hook
from application.models.user import User
from application.models.forms import LoginForm, RequestPasswordForm, ResetPasswordForm
from application.modules.email import send_email


AUTH_RATE_LIMIT = app.config.get('AUTH_RATE_LIMIT', '3 per minute; 10 per hour')
AUTH = Blueprint('auth', __name__)


@AUTH.errorhandler(429)
def ratelimit_handler(_error):
    """Generic message on rate-limit hit; details intentionally omitted."""
    flash('Too many attempts. Please wait a moment and try again.', 'danger')
    return redirect(request.path)

@login_manager.user_loader
def load_user(user_id):
    """
    Flask Login: Load User
    """
    try:
        return User.objects.get(id=user_id)
    except DoesNotExist:
        return None

@AUTH.route('/login', methods=['GET', 'POST'])
@limiter.limit(AUTH_RATE_LIMIT, methods=['POST'])
def login():  # pylint: disable=too-many-return-statements,too-many-branches
    """
    Login Route
    """
    if current_user.is_authenticated:
        flash('Already Logged in')
        return redirect(url_for("admin.index"))

    if app.config['REMOTE_USER_LOGIN'] and request.remote_user:
        try:
            existing_user = run_hook('remote_user', request)
            if existing_user:
                session.clear()
                login_user(
                    existing_user,
                    remember=False,
                    duration=timedelta(
                        hours=(current_app.config['ADMIN_SESSION_HOURS'] or 8)
                    )
                )
                existing_user.last_login = datetime.now()
                existing_user.save()
                return redirect(url_for("admin.index"))
        except Exception:  # pylint: disable=broad-exception-caught
            log.log("Remote User login failed", source="AUTH")
            flash('Remote User Error', 'danger')


    login_form = LoginForm(request.form)

    context = {
        'LoginForm' : login_form,
    }
    if login_form.login_submit.data and login_form.validate_on_submit():
        email = login_form.login_email.data.lower()
        password = login_form.password.data
        otp = login_form.otp.data
        user_result = User.objects(email=email, disabled__ne=True)
        if user_result:
            existing_user = user_result[0]
        else:
            existing_user = False

        ldap_authenticated = False
        if app.config['LDAP_LOGIN']:
            try:
                ldap_user = run_hook('ldap_login', email, password)
                if ldap_user:
                    existing_user = ldap_user
                    ldap_authenticated = True
            except Exception:  # pylint: disable=broad-exception-caught
                log.log("LDAP login failed", source="AUTH")
                flash('LDAP Error', 'danger')
                return render_template('login.html', **context)

        # Always wrong Password, even when user not exists
        local_ok = existing_user and existing_user.check_password(password)
        if not ldap_authenticated and not local_ok:
            flash("Wrong Password", 'danger')
            return render_template('login.html', **context)

        if existing_user.disabled:
            flash("User Disabled", 'danger')
            return render_template('login.html', **context)

        if existing_user.tfa_secret:
            if not otp:
                flash("2FA Secret missing", 'danger')
                return render_template('login.html', **context)
            if not pyotp.TOTP(existing_user.tfa_secret).verify(otp):
                flash("Invalid 2FA Token", 'danger')
                return render_template('login.html', **context)



        session.clear()
        login_user(
            existing_user,
            remember=False,
            duration=timedelta(
                hours=(current_app.config['ADMIN_SESSION_HOURS'] or 8)
            )
        )
        existing_user.last_login = datetime.now()
        existing_user.save()
        if existing_user.force_password_change:
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("admin.index"))

    return render_template('login.html', **context)


@AUTH.route('/set-2fa', methods=['GET', 'POST'])
@login_required
def set_2fa():
    """
    SET 2FA Code for User
    """

    secret = request.form.get("secret")
    otp = request.form.get("otp")
    form = {
        'secret': pyotp.random_base32(),
    }

    # Use existing secret for useres who not make it on first try
    if secret:
        form['secret'] = secret

    if otp:
        if pyotp.TOTP(secret).verify(otp):
            flash("New 2FA Secret Set", "success")
            current_user.tfa_secret = secret
            current_user.save()
            return redirect(url_for("admin.index"))
        flash("You have supplied an invalid 2FA token!", "danger")

    return render_template("set_2fa.html", form=form)

@AUTH.route('/logout')
@login_required
def logout():
    """
    Session cleanup and logout
    """
    session.clear()
    logout_user()
    return redirect(url_for("admin.index"))


@AUTH.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Change Password Route
    """
    form = ResetPasswordForm(request.form)
    if form.validate_on_submit():
        password = request.form.get('password')
        current_user.set_password(password)
        current_user.lastLogin = datetime.now()
        current_user.force_password_change = False
        current_user.save()
        return redirect(url_for("admin.index"))
    if form.errors:
        for _, message in form.errors.items():
            flash(message[0], 'danger')

    return render_template('formular.html', form=form)

@AUTH.route('/request-password', methods=['GET', 'POST'])
@limiter.limit(AUTH_RATE_LIMIT, methods=['POST'])
def request_password():
    """
    Password Request Page
    """
    form = RequestPasswordForm(request.form)
    if form.validate_on_submit():
        email = form.request_email.data.lower()
        user_result = User.objects(email=email)
        if user_result:
            existing_user = user_result[0]
            token = existing_user.generate_token(purpose='pw_reset')
            send_email(existing_user.email, "New Password", 'email/resetpassword',
                       user=existing_user, token=token)
        flash("New Password will be sent", 'info')
        return redirect(url_for("admin.index"))

    return render_template('formular.html', form=form)

def get_userid(token, purpose):
    """
    Helper to read Userid from token. Verifies expiry, purpose claim, and
    that the token's pwd_iat still matches the user's current date_password
    (so a token becomes invalid as soon as the password is changed).
    """
    key = current_app.config['SECRET_KEY']
    try:
        data = jwt.decode(token, key)
        if 'exp' in data:
            now = datetime.utcnow().timestamp()
            if now > data['exp']:
                raise ValueError("Token Expired")
    except JoseError as error:
        raise ValueError(error) from error

    if not data:
        return None
    if data.get('purpose') != purpose:
        return None

    user_id = data.get('userid')
    if not user_id:
        return None

    try:
        existing_user = User.objects.get(id=user_id)
    except DoesNotExist:
        return None

    current_pwd_iat = (
        int(existing_user.date_password.timestamp())
        if existing_user.date_password else 0
    )
    if data.get('pwd_iat') != current_pwd_iat:
        return None

    return user_id

@AUTH.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """ Reset Password Route"""
    form = ResetPasswordForm(request.form)
    try:
        user_id = get_userid(token, purpose='pw_reset')
    except ValueError:
        user_id = None
    if not user_id:
        flash("Invalid Link", "danger")
        return redirect(url_for("admin.index"))

    user_result = User.objects(id=user_id)
    if user_result:
        existing_user = user_result[0]
    else:
        flash("User Uknown", "danger")
        return redirect("/")

    if form.validate_on_submit():
        password = request.form.get('password')
        existing_user.set_password(password)
        existing_user.lastLogin = datetime.now()
        existing_user.save()
        session.clear()
        login_user(
            existing_user,
            duration=timedelta(
                hours=(current_app.config['ADMIN_SESSION_HOURS'] or 8)
            )
        )
        flash("Password Changed", 'success')
        return redirect(url_for("admin.index"))
    if form.errors:
        for _, message in form.errors.items():
            flash(message[0], 'danger')

    return render_template('formular.html', form=form)
