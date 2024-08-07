"""
Login Routes
"""
# pylint: disable=no-member
from datetime import datetime
from datetime import timedelta
import pyotp
from flask import request, render_template, current_app, \
     flash, redirect, session, Blueprint, url_for
from flask_login import current_user, login_user, logout_user, login_required
from authlib.jose import jwt, JoseError

from application import login_manager

from application.models.user import User
from application.models.forms import LoginForm, RequestPasswordForm, ResetPasswordForm
from application.modules.email import send_email
from mongoengine.errors import DoesNotExist


AUTH = Blueprint('auth', __name__)

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
def login():
    """
    Login Route
    """
    if current_user.is_authenticated:
        flash('Already Logged in')
        return redirect(url_for("admin.index"))

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

        # Always wrong Password, even when user not exists
        if not (existing_user and existing_user.check_password(password)):
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
            token = existing_user.generate_token()
            send_email(existing_user.email, "New Password", 'email/resetpassword',
                       user=existing_user, token=token)
        flash("New Password will be sent", 'info')
        return redirect(url_for("admin.index"))

    return render_template('formular.html', form=form)

def get_userid(token):  # pylint: disable=inconsistent-return-statements
    """
    Helper to read Userid from token
    """
    key = current_app.config['SECRET_KEY']
    try:
        data = jwt.decode(token, key)
        if 'exp' in data:
            now = datetime.utcnow().timestamp()
            if now > data['exp']:
                raise ValueError("Token Expired")

    except JoseError as error:
        raise ValueError(error)
    if data:
        return data.get('userid')

@AUTH.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """ Reset Password Route"""
    form = ResetPasswordForm(request.form)
    user_id = get_userid(token)
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
