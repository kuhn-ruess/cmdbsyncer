"""
Models Config
"""
import os

from flask import flash, redirect, request, url_for
from flask_admin import expose
from flask_login import current_user

from application import app
from application.config import BaseConfig
from application.helpers.local_config_file import (
    LocalConfigError, delete_key, is_writable, load, set_key,
)
from application.helpers.local_config_presets import PRESETS, get_preset
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
    'AUTH_RATE_LIMIT', 'RATELIMIT_STORAGE_URI', 'HOST_PAGESIZE',
    'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USE_TLS', 'MAIL_USE_SSL',
    'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_SENDER', 'MAIL_SUBJECT_PREFIX',
    'SESSION_COOKIE_NAME', 'SESSION_COOKIE_SECURE',
    'SESSION_COOKIE_HTTPONLY', 'SESSION_COOKIE_SAMESITE',
    'ADMIN_SESSION_HOURS', 'BASE_PREFIX',
    'TRUSTED_PROXIES', 'ALLOW_INSECURE_API_AUTH', 'REQUIRE_HTTPS',
    'LDAP_SERVER', 'LDAP_USER_DN_TEMPLATE',
    'LDAP_BIND_USER', 'LDAP_BIND_PASSWORD',
    'LDAP_SEARCH_BASE', 'LDAP_SEARCH_FILTER',
    'LDAP_REQUIRED_GROUP', 'LDAP_NAME_ATTR', 'LDAP_AUTO_CREATE',
    'SWAGGER_ENABLED',
})


_MISSING = object()


def _local_config_path():
    """`local_config.py` lives next to the app root."""
    return os.path.join(os.path.dirname(app.root_path), 'local_config.py')


def _baseconfig_default(key):
    """Return the BaseConfig (or Flask) default for *key*, or ``_MISSING``."""
    if hasattr(BaseConfig, key):
        return getattr(BaseConfig, key)
    if key in app.default_config:
        return app.default_config[key]
    return _MISSING


def _restore_runtime_default(key):
    """Drop the override and restore the static default.

    Flask reads many config keys lazily at request time
    (``SESSION_COOKIE_*`` etc.) — popping them outright leaves Flask
    with a ``KeyError`` on the next request. Re-applying the
    ``BaseConfig`` / Flask default keeps the running app consistent
    with what a fresh restart would produce.
    """
    default = _baseconfig_default(key)
    if default is _MISSING:
        app.config.pop(key, None)
    else:
        app.config[key] = default


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
    def local_config_editor(self):  # pylint: disable=too-many-branches,too-many-locals
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
                elif action == 'apply_preset':
                    self._do_apply_preset(path)
                elif action == 'delete_group':
                    self._do_delete_group(path)
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
            value = entries[key]
            is_protected = key in PROTECTED_KEYS
            rows.append({
                'key': key,
                # Never expose the current value of a protected key in
                # the rendered HTML — the input stays blank, an empty
                # submit means "no change", any non-empty value
                # overwrites.
                'value': '' if is_protected else value,
                'type': _type_of(value),
                'restart_only': key in RESTART_ONLY_KEYS,
                'is_protected': is_protected,
            })

        # Group the existing entries the same way the Quick configurations
        # do, so admins can scan related settings together. Keys that are
        # not part of any preset land in a final ``Other`` bucket.
        key_to_preset = {
            entry['key']: preset['ident']
            for preset in PRESETS for entry in preset['keys']
        }
        grouped_buckets = {
            preset['ident']: {'name': preset['name'], 'rows': []}
            for preset in PRESETS
        }
        grouped_buckets['_other'] = {'name': 'Other', 'rows': []}
        for row in rows:
            grouped_buckets[key_to_preset.get(row['key'], '_other')]['rows'].append(row)
        grouped_rows = [
            {'ident': ident, 'name': bucket['name'], 'rows': bucket['rows']}
            for ident, bucket in grouped_buckets.items() if bucket['rows']
        ]

        # Annotate each preset key so the template knows whether the
        # value already exists in local_config.py — admins can spot at a
        # glance which fields the snippet would overwrite.
        existing_keys = set(entries)
        presets_view = []
        for preset in PRESETS:
            preset_keys = []
            overlap = 0
            for entry in preset['keys']:
                exists = entry['key'] in existing_keys
                preset_keys.append({**entry, 'exists': exists})
                if exists:
                    overlap += 1
            presets_view.append({
                **preset,
                'keys': preset_keys,
                'overlap': overlap,
                'total': len(preset['keys']),
            })

        return self.render(
            'admin/local_config_editor.html',
            grouped_rows=grouped_rows,
            path=path,
            writable=writable,
            presets=presets_view,
        )

    # ---------- action handlers -----------------------------------------

    def _do_update(self, path, key):
        if not key:
            raise LocalConfigError("Missing key")
        value_type = (request.form.get('type') or 'str').strip()
        raw_value = request.form.get('value', '')
        # Protected keys are rendered with a blank input — the current
        # value never reaches the browser. An empty submit therefore
        # means "leave it untouched"; only a non-empty value overwrites.
        if key in PROTECTED_KEYS and value_type == 'str' and not raw_value:
            flash(f'{key}: no change (empty value left as-is)', 'info')
            return
        coerced = _coerce(raw_value, value_type)
        set_key(path, key, coerced)
        self._apply_runtime(key, coerced)
        self._flash_saved(key)

    def _do_add(self, path, key):
        if not key:
            raise LocalConfigError("Missing key")
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
        _restore_runtime_default(key)
        flash(f'Deleted {key}', 'success')

    def _do_delete_group(self, path):
        """
        Remove every preset-managed key in *group* from local_config.py.
        Protected keys are kept (delete is intentionally blocked for
        them in this view; remove them on disk if really needed).
        """
        ident = (request.form.get('group') or '').strip()
        preset = get_preset(ident)
        if preset is None:
            raise LocalConfigError(f"Unknown group: {ident!r}")

        existing = load(path)
        deleted = []
        skipped_protected = []
        for entry in preset['keys']:
            key = entry['key']
            if key not in existing:
                continue
            if key in PROTECTED_KEYS:
                skipped_protected.append(key)
                continue
            delete_key(path, key)
            _restore_runtime_default(key)
            deleted.append(key)

        if deleted:
            flash(
                f"Removed {len(deleted)} key(s) from '{preset['name']}': "
                f"{', '.join(deleted)}",
                'success',
            )
        if skipped_protected:
            flash(
                f"Kept protected keys (edit local_config.py on disk to "
                f"remove): {', '.join(skipped_protected)}",
                'warning',
            )
        if not deleted and not skipped_protected:
            flash(f"No keys from '{preset['name']}' were set", 'info')

    def _do_apply_preset(self, path):
        """
        Persist every key from a preset in one go. Empty ``str`` values
        are silently skipped — the admin meant "don't set this"
        (especially for protected keys like ``MAIL_PASSWORD`` whose
        existing value is intentionally not echoed back).
        """
        ident = (request.form.get('preset') or '').strip()
        preset = get_preset(ident)
        if preset is None:
            raise LocalConfigError(f"Unknown preset: {ident!r}")

        applied = []
        skipped_default = []
        restart_only = False
        for entry in preset['keys']:
            key = entry['key']
            value_type = entry['type']
            field_name = f"value__{key}"
            if field_name not in request.form:
                continue
            raw_value = request.form.get(field_name, '')
            # Empty string for str-typed fields = "leave alone".
            # Particularly important for protected keys whose current
            # value is never pre-filled, so the form arrives empty by
            # design unless the admin types something new.
            if value_type == 'str' and not raw_value.strip():
                continue
            coerced = _coerce(raw_value, value_type)
            # Don't pollute local_config.py with values that match the
            # BaseConfig default — they'd just be noise the admin has
            # to delete later.
            if coerced == _baseconfig_default(key):
                skipped_default.append(key)
                continue
            set_key(path, key, coerced)
            self._apply_runtime(key, coerced)
            applied.append(key)
            if key in RESTART_ONLY_KEYS:
                restart_only = True

        if applied:
            msg = f"Applied preset '{preset['name']}': {', '.join(applied)}"
            if restart_only:
                msg += '. Restart required for some keys to take effect.'
            flash(msg, 'warning' if restart_only else 'success')
        if skipped_default:
            flash(
                f"Skipped (already at default): {', '.join(skipped_default)}",
                'info',
            )

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
