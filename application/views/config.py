"""
Models Config
"""
import os

from flask import flash, redirect, request, url_for
from flask_admin import expose
from flask_login import current_user

from application import app
from application.helpers.local_config_file import (
    LocalConfigError, delete_key, is_writable, load, set_key,
)
from application.helpers.sates import remove_changes
from application.plugins.maintenance import clear_host_caches
from application.views.default import DefaultModelView


# Keys never shown in the editor. The real values stay in
# local_config.py untouched — we just don't let admins edit them from
# the web UI because changing them online either breaks existing
# sessions or silently defuses security defaults.
PROTECTED_KEYS = frozenset({
    'SECRET_KEY',
    'CRYPTOGRAPHY_KEY',
    'MONGODB_SETTINGS',
    'MONGODB_HOST',
    'MONGODB_PORT',
    'MONGODB_DB',
    'MAIL_PASSWORD',
    'LDAP_BIND_PASSWORD',
})

# Keys that take effect only after a restart. We still let admins set
# them, but flash a notice so expectations match reality.
RESTART_ONLY_KEYS = frozenset({
    'DEBUG', 'FILEADMIN_PATH',
    'REMOTE_USER_LOGIN', 'LDAP_LOGIN', 'OIDC_LOGIN',
    'SENTRY_ENABLED', 'SENTRY_DSN',
    'AUTH_RATE_LIMIT', 'HOST_PAGESIZE',
    'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USE_TLS', 'MAIL_USE_SSL',
    'MAIL_USERNAME', 'MAIL_SENDER', 'MAIL_SUBJECT_PREFIX',
    'SESSION_COOKIE_NAME', 'SESSION_COOKIE_SECURE',
    'TRUSTED_PROXIES', 'ALLOW_INSECURE_API_AUTH',
})


def _local_config_path():
    """`local_config.py` lives next to the app root."""
    return os.path.join(os.path.dirname(app.root_path), 'local_config.py')


def _coerce(raw_value, value_type):
    """
    Turn a form-submitted string into the typed primitive the admin
    asked for. `raw_value` is always a string (from the HTML form);
    `value_type` is one of 'str' / 'int' / 'float' / 'bool' / 'none'.
    """
    if value_type == 'none':
        return None
    if value_type == 'str':
        return raw_value
    if value_type == 'int':
        return int(raw_value)
    if value_type == 'float':
        return float(raw_value)
    if value_type == 'bool':
        return raw_value.strip().lower() in ('1', 'true', 'yes', 'on')
    raise LocalConfigError(f"Unknown type {value_type!r}")


def _type_of(value):
    """Inverse of `_coerce` — what the editor should display as the type."""
    if value is None:
        return 'none'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'float'
    return 'str'


class ConfigModelView(DefaultModelView):
    """
    Config View
    """
    page_size = 1
    can_delete = False
    can_create = False

    @expose('/commit_changes', methods=('POST',))
    def commit_changes(self):
        """
        Delete all Caches
        """
        remove_changes()
        clear_host_caches()
        return "Activation Done"

    # ------------------------------------------------------------------
    # local_config.py editor
    # ------------------------------------------------------------------

    @expose('/local_config', methods=('GET', 'POST'))
    def local_config_editor(self):  # pylint: disable=too-many-branches
        """
        Key/value editor for `local_config.py`. Actions are mutually
        exclusive and dispatched by a hidden `_action` field so a bad
        click cannot accidentally wipe values.
        """
        path = _local_config_path()

        if request.method == 'POST':
            action = (request.form.get('_action') or '').strip()
            key = (request.form.get('key') or '').strip()
            try:
                if action == 'update':
                    self._do_update(path, key)
                elif action == 'add':
                    self._do_add(path, key)
                elif action == 'delete':
                    self._do_delete(path, key)
                else:
                    flash(f'Unknown action: {action!r}', 'error')
            except LocalConfigError as exp:
                flash(str(exp), 'error')
            except ValueError as exp:
                # e.g. int('abc')
                flash(f'Invalid value: {exp}', 'error')
            return redirect(url_for('.local_config_editor'))

        try:
            entries = load(path)
        except LocalConfigError as exp:
            flash(str(exp), 'error')
            entries = {}

        writable = is_writable(path)
        if not writable:
            directory = os.path.dirname(path) or '.'
            flash(
                f"{path} is not writable by the syncer OS user. "
                f"Reads work, but any save will fail. Fix the filesystem "
                f"permissions on the file and its parent directory "
                f"({directory}) before editing.",
                'error',
            )

        rows = []
        for key in sorted(entries):
            if key in PROTECTED_KEYS:
                continue
            value = entries[key]
            rows.append({
                'key': key,
                'value': value,
                'type': _type_of(value),
                'restart_only': key in RESTART_ONLY_KEYS,
            })

        # Protected keys are shown in a separate, read-only panel so
        # admins know they exist without letting them be edited here.
        protected_rows = sorted(k for k in entries if k in PROTECTED_KEYS)

        return self.render(
            'admin/local_config_editor.html',
            rows=rows,
            protected_rows=protected_rows,
            path=path,
            writable=writable,
        )

    # ---------- action handlers -----------------------------------------

    def _do_update(self, path, key):
        if not key:
            raise LocalConfigError("Missing key")
        value_type = (request.form.get('type') or 'str').strip()
        raw_value = request.form.get('value', '')
        coerced = _coerce(raw_value, value_type)
        set_key(path, key, coerced)
        self._apply_runtime(key, coerced)
        self._flash_saved(key)

    def _do_add(self, path, key):
        if not key:
            raise LocalConfigError("Missing key")
        if key in PROTECTED_KEYS:
            raise LocalConfigError(
                f"Key {key!r} is protected and cannot be set from the UI"
            )
        existing = load(path)
        if key in existing:
            raise LocalConfigError(
                f"Key {key!r} already exists — edit the existing row instead"
            )
        value_type = (request.form.get('type') or 'str').strip()
        raw_value = request.form.get('value', '')
        coerced = _coerce(raw_value, value_type)
        set_key(path, key, coerced)
        self._apply_runtime(key, coerced)
        flash(f'Added {key}', 'success')

    def _do_delete(self, path, key):
        if not key:
            raise LocalConfigError("Missing key")
        if key in PROTECTED_KEYS:
            raise LocalConfigError(
                f"Key {key!r} is protected and cannot be deleted from the UI"
            )
        delete_key(path, key)
        # Runtime: drop the override so any BaseConfig default re-surfaces.
        app.config.pop(key, None)
        flash(f'Deleted {key}', 'success')

    # ---------- helpers ------------------------------------------------

    def _apply_runtime(self, key, value):
        """Hot-reload into the running `app.config` for non-restart keys."""
        if key in RESTART_ONLY_KEYS:
            return
        if value is None:
            app.config.pop(key, None)
        else:
            app.config[key] = value

    def _flash_saved(self, key):
        if key in RESTART_ONLY_KEYS:
            flash(
                f'Saved {key}. A service restart is required before the '
                f'new value takes effect.',
                'warning',
            )
        else:
            flash(f'Saved {key} (applied live)', 'success')

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin
