from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, RadioField, SubmitField, BooleanField, \
                    TextAreaField, HiddenField, DateField, SelectMultipleField, IntegerField
from wtforms.validators import InputRequired, Email, EqualTo, ValidationError
from mongoengine.errors import NotUniqueError, DoesNotExist
from wtforms.widgets import TextArea
from flask import current_app
import re


def validate_password(form, field):
    password = field.data
    if hasattr(form, 'old_password') and form.old_password.data == password:
        raise ValidationError(_('password_old_new_not_match'))

    passwd_length = current_app.config['PASSWD_MIN_PASSWD_LENGTH']
    if len(password) < passwd_length:
        raise ValidationError("Password to short")

    not_matching = 0
    total_tests = 0
    if current_app.config['PASSWD_SPECIAL_CHARS']:
        total_tests += 1
        if not re.search(r"[ ?!#$%&'()*+,-./[\\\]^_`{|}~"+r'"]', password):
            not_matching += 1

    if current_app.config['PASSWD_SPECIAL_DIGITS']:
        total_tests += 1
        if not re.search(r"\d", password):
            not_matching += 1

    if current_app.config['PASSWD_SEPCIAL_UPPER']:
        total_tests += 1
        if not re.search(r"[A-Z]", password):
            not_matching += 1

    if current_app.config['PASSWD_SEPCIAL_LOWER']:
        total_tests += 1
        if not re.search(r"[a-z]", password):
            not_matching += 1
    matches = total_tests - not_matching

    if matches <= current_app.config['PASSWD_SPECIAL_NEEDED']:
        raise ValidationError("Unsave Password")

class LoginForm(FlaskForm):
    login_email = StringField("E-Mail", [InputRequired(), Email()])
    password = PasswordField("Password", [InputRequired()])
    otp = StringField("OTP")
    login_submit   = SubmitField("Login")

class RequestPasswordForm(FlaskForm):
    request_email = StringField("E-Mail", [InputRequired(), Email()])
    request_submit   = SubmitField("Send")

class ResetPasswordForm(FlaskForm):
    password  = PasswordField("New Password", validators=[InputRequired(),validate_password, EqualTo('password_repeat')])
    password_repeat = PasswordField("Password repeat", validators=[InputRequired()])
    submit = SubmitField("Send")
