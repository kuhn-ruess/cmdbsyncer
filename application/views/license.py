"""
License Information View
"""
import importlib.util
import os
from datetime import datetime
from pathlib import Path

from flask import flash, redirect, request, url_for
from flask_admin import BaseView, expose
from flask_login import current_user

from application import enterprise
from application.enterprise import run_hook


# Hard cap on the uploaded file size. JWTs are ~1-2 KB; anything bigger
# is either malformed or a stray attachment, not a license.
_MAX_LICENSE_BYTES = 16 * 1024


def _resolve_destination():
    """Pick the same destination the enterprise loader reads from."""
    env_path = os.environ.get('CMDBSYNCER_LICENSE')
    if env_path:
        return env_path
    spec = importlib.util.find_spec('local_config')
    if spec and spec.origin:
        return str(Path(spec.origin).parent / 'license.jwt')
    return None


def _enterprise_pubkey_path():
    """
    Locate `public_key.pem` inside the installed enterprise package
    *without* importing the package — its `__init__` may raise when the
    current license is bad, but the key file itself is always on disk.
    """
    spec = importlib.util.find_spec('cmdbsyncer_enterprise')
    if not spec or not spec.origin:
        return None
    return Path(spec.origin).parent / 'public_key.pem'


def _read_and_verify_upload(upload):
    """
    Read the uploaded license file and verify its signature.

    Returns ``(token, None)`` on success or ``(None, error_message)``
    on any failure. Keeps the upload view free of validation branching.
    """
    if not upload or not upload.filename:
        return None, 'No license file selected'
    raw = upload.read(_MAX_LICENSE_BYTES + 1)
    if len(raw) > _MAX_LICENSE_BYTES:
        return None, 'License file is too large to be a valid JWT'
    token = raw.decode('utf-8', errors='replace').strip()
    if not token:
        return None, 'Uploaded license file is empty'

    pubkey_path = _enterprise_pubkey_path()
    if pubkey_path is None or not pubkey_path.exists():
        return None, 'Enterprise package is not installed — cannot upload a license'

    # joserfc is in OSS requirements, but only used here on demand.
    from joserfc import jwt  # pylint: disable=import-outside-toplevel
    from joserfc.jwk import RSAKey  # pylint: disable=import-outside-toplevel
    from joserfc.errors import JoseError  # pylint: disable=import-outside-toplevel
    try:
        key = RSAKey.import_key(pubkey_path.read_bytes())
        jwt.decode(token, key, algorithms=['RS256'])
    except JoseError as exp:
        return None, f'License signature invalid: {exp}'
    return token, None


class LicenseView(BaseView):
    """
    Show Enterprise License Information
    """

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin

    @expose('/')
    def index(self):
        """
        Render license info page
        """
        info = run_hook('license_info')
        exp_ts = info.get('exp') if info else None
        exp_human = datetime.fromtimestamp(exp_ts).strftime('%Y-%m-%d %H:%M:%S') \
            if isinstance(exp_ts, (int, float)) else None
        package_installed = importlib.util.find_spec('cmdbsyncer_enterprise') is not None
        registry_features = sorted(enterprise._features)  # pylint: disable=protected-access
        registry_hooks = sorted(enterprise._hooks.keys())  # pylint: disable=protected-access
        return self.render('license_info.html',
                           license=info,
                           exp_human=exp_human,
                           package_installed=package_installed,
                           load_status=enterprise.load_status,
                           registry_features=registry_features,
                           registry_hooks=registry_hooks,
                           license_destination=_resolve_destination())

    @expose('/upload', methods=['POST'])
    def upload(self):
        """
        Replace the active license.jwt with an uploaded file.

        Verifies the JWT signature against the public key shipped with
        the enterprise package before writing, so a corrupt or wrongly
        signed upload never overwrites a working license. The new file
        is only loaded by the application on the next start; the user
        is told so via flash.
        """
        if not (current_user.is_authenticated and current_user.global_admin):
            return redirect(url_for('admin.login_view'))

        token, error = _read_and_verify_upload(request.files.get('license_file'))
        if error:
            flash(error, 'error')
            return redirect(url_for('license.index'))

        dest = _resolve_destination()
        if dest is None:
            flash(
                'Cannot resolve license destination: set CMDBSYNCER_LICENSE '
                'or place local_config.py on sys.path',
                'error',
            )
            return redirect(url_for('license.index'))

        # Atomic write: stage to a sibling .tmp, then rename. A failure
        # mid-write leaves the previously active license untouched.
        dest_path = Path(dest)
        tmp_path = dest_path.parent / (dest_path.name + '.tmp')
        try:
            tmp_path.write_text(token, encoding='ascii')
            tmp_path.replace(dest_path)
        except OSError as exp:
            flash(f'Cannot write license file ({dest}): {exp}', 'error')
            return redirect(url_for('license.index'))

        flash(
            f'License saved to {dest}. Restart the application to activate.',
            'success',
        )
        return redirect(url_for('license.index'))
