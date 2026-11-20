"""
Settings, LDAP Login: what the LDAP login runs with, the LDAP settings to
edit, and a test login of a directory user against them, step by step.
Only there with the licensed enterprise LDAP login.
"""
from flask import flash, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application import app, log
from application.docu_links import docu_links
from application.enterprise import has_feature, run_hook
from application.helpers.local_config_file import LocalConfigError, is_writable, load
from application.views.config import (
    PROTECTED_KEYS,
    _ldap_check_config,
    _local_config_path,
    _presets_view,
    apply_preset,
    role_mapping_from_form,
)


def run_login_test(config, login, password):
    """
    Walk the LDAP login of `login` with `config` and log the result under
    source AUTH. Returns {'ok':, 'steps': [{'ok':, 'text':, 'details':,
    'hint':}]}. Nothing else is written.
    """
    login = (login or '').strip().lower()
    if not has_feature('ldap_check_login'):
        return {'ok': False, 'steps': [{
            'ok': False, 'text': 'The LDAP login test is not available',
            'hint': 'It needs the enterprise feature ldap_login, '
                    'cmdbsyncer-enterprise 0.4.5 or newer.'}]}
    result = run_hook('ldap_check_login', config, login, password or '')
    last = result['steps'][-1] if result['steps'] else {}
    details = [('tested_by', current_user.email), ('login', login),
               ('result', last.get('text', ''))]
    if not result['ok']:
        details.append(('error', last.get('details', {}).get('error')
                        or last.get('hint') or last.get('text', '')))
    log.log(f"LDAP login test for {login}: "
            f"{'success' if result['ok'] else 'failed'}",
            source='AUTH', details=details)
    return result


def _preconditions():
    """
    What has to hold for the login page to try LDAP at all, as rows of
    (ok, text, hint). When one fails, the login page silently checks the
    local password only and answers "Wrong Password".
    """
    rows = [
        (has_feature('ldap_check_login'), "Login test available",
         "Update cmdbsyncer-enterprise to 0.4.5 or newer and restart."),
        (bool(app.config.get('LDAP_LOGIN')), "LDAP_LOGIN is on",
         "Set LDAP_LOGIN to true below, save and restart."),
    ]
    return [{'ok': ok, 'text': text, 'hint': None if ok else hint}
            for ok, text, hint in rows]


def _settings():
    """The LDAP settings the login runs with, never a password"""
    config = app.config
    template = config.get('LDAP_USER_DN_TEMPLATE')
    rows = [
        ('Server', config.get('LDAP_SERVER') or 'not set'),
        ('Mode', 'direct bind with LDAP_USER_DN_TEMPLATE' if template
         else 'search with the service account'),
    ]
    if template:
        rows.append(('User DN template', template))
    else:
        rows += [
            ('Service account', config.get('LDAP_BIND_USER') or 'not set'),
            ('Service password', 'set' if config.get('LDAP_BIND_PASSWORD') else 'not set'),
            ('Search base', config.get('LDAP_SEARCH_BASE') or 'not set'),
            ('Search filter', config.get('LDAP_SEARCH_FILTER') or ''),
        ]
    mapping = config.get('LDAP_ROLE_MAPPING') or {}
    rows += [
        ('CA file', config.get('LDAP_TLS_CA_FILE') or 'CAs of the system'),
        ('Required group', config.get('LDAP_REQUIRED_GROUP') or 'none'),
        ('Name attribute', config.get('LDAP_NAME_ATTR') or 'cn'),
        ('Create local users', 'yes' if config.get('LDAP_AUTO_CREATE', True) else 'no'),
        ('Role mapping', f"{len(mapping)} group(s)" if mapping else 'none, roles stay as set'),
        ('AUTH_DEBUG', 'on' if config.get('AUTH_DEBUG') else 'off'),
    ]
    return rows


def _ldap_preset(entries, form=None):
    """
    The LDAP card with the saved values, or with the values of a form
    that was only tested. A protected value never goes to the browser.
    """
    preset = next(p for p in _presets_view(entries) if p['ident'] == 'ldap')
    if form:
        for entry in preset['keys']:
            field = f"value__{entry['key']}"
            if entry['type'] == 'role_mapping' and field in form:
                entry['value'] = role_mapping_from_form(form, entry['key'])
            elif field in form and entry['key'] not in PROTECTED_KEYS:
                raw = form[field]
                entry['value'] = raw == 'true' if entry['type'] == 'bool' else raw
    return preset


def _waiting_for_restart(entries):
    """LDAP keys whose saved value the running application does not use yet"""
    keys = [entry['key'] for entry in _ldap_preset({})['keys']]
    return [key for key in keys if key in entries and entries[key] != app.config.get(key)]


class LdapLoginTestView(BaseView):
    """Settings, LDAP Login"""

    @expose('/', methods=('GET', 'POST'))
    def index(self):
        """Preconditions, the LDAP settings, a test login and saving"""
        path = _local_config_path()
        action = request.form.get('_action') if request.method == 'POST' else None
        if action == 'save':
            try:
                apply_preset(path, 'ldap')
            except (LocalConfigError, ValueError) as error:
                flash(f'Not saved: {error}', 'error')
            return redirect(url_for('.index'))

        result = None
        login = ''
        if action == 'test':
            login = request.form.get('login', '')
            result = run_login_test(_ldap_check_config(), login,
                                    request.form.get('password', ''))
        try:
            entries = load(path)
        except LocalConfigError as error:
            flash(str(error), 'error')
            entries = {}
        return self.render('admin/ldap_login_test.html',
                           preconditions=_preconditions(),
                           settings=_settings(),
                           preset=_ldap_preset(entries, request.form if action else None),
                           waiting=_waiting_for_restart(entries),
                           writable=is_writable(path),
                           result=result,
                           login=login,
                           # A tested service password is not sent back
                           password_dropped=bool(action == 'test' and request.form.get(
                               'value__LDAP_BIND_PASSWORD', '').strip()),
                           docs_url=docu_links['ent_ldap_login'])

    def is_accessible(self):
        return (current_user.is_authenticated and current_user.global_admin
                and has_feature('ldap_login'))

    def is_visible(self):
        return has_feature('ldap_login')
