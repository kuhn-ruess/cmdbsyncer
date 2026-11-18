"""
LDAP Login Test: what the LDAP login runs with, and a test login of a
directory user against exactly that, step by step
"""
from flask import request
from flask_admin import BaseView, expose
from flask_login import current_user

from application import app, log
from application.docu_links import docu_links
from application import enterprise
from application.enterprise import has_feature, run_hook


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
    status = enterprise.load_status or 'not installed'
    rows = [
        (status == 'active', f"Enterprise package: {status}",
         "Install cmdbsyncer-enterprise and a license, then restart the application."),
        (has_feature('ldap_login'), "Feature ldap_login licensed",
         "The license has to include ldap_login, see Settings, License."),
        (has_feature('ldap_check_login'), "Login test available",
         "Update cmdbsyncer-enterprise to 0.4.5 or newer and restart."),
        (bool(app.config.get('LDAP_LOGIN')), "LDAP_LOGIN is on",
         "Switch on LDAP_LOGIN in local_config.py and restart."),
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


class LdapLoginTestView(BaseView):
    """Settings, LDAP Login Test"""

    @expose('/', methods=('GET', 'POST'))
    def index(self):
        """Preconditions, settings, and the test form with its result"""
        result = None
        login = ''
        if request.method == 'POST':
            login = request.form.get('login', '')
            result = run_login_test(app.config, login, request.form.get('password', ''))
        return self.render('admin/ldap_login_test.html',
                           preconditions=_preconditions(),
                           settings=_settings(),
                           result=result,
                           login=login,
                           docs_url=docu_links['ent_ldap_login'])

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin
