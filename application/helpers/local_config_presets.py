"""
Pre-canned configuration snippets for the ``local_config.py`` editor.

Each preset bundles a set of related primitive keys with sensible
defaults. The editor renders one form per preset; the admin can tweak
each default before saving, so a snippet is a starting point, not a
fixed payload.

Only primitive values (str / int / float / bool / None) are usable — the
editor refuses anything else. Nested dicts (like ``LOGGING``) are
intentionally not offered as snippets; edit them in ``local_config.py``
by hand.
"""

# Each entry in ``keys`` is ``{key, type, default, hint?}``:
#   key     — the local_config.py dict key (UPPER_CASE convention).
#   type    — one of 'str' / 'int' / 'float' / 'bool' / 'none'; same set
#             the editor's ``_coerce`` accepts.
#   default — the value pre-filled in the form. Strings only need
#             quoting in the file, never in the form.
#   hint    — optional short help line shown below the input.

PRESETS = [
    {
        'ident': 'mail',
        'name': 'Mail (SMTP)',
        'description': (
            "Outbound email used for password reset and the "
            "Notifications module. Flask-Mail picks up the MAIL_* keys "
            "directly; MAIL_SENDER and MAIL_SUBJECT_PREFIX are read by "
            "application/modules/email.py."
        ),
        'note': (
            "MAIL_PASSWORD is on the protected list — its current value "
            "is never echoed back into this form. Type a new value to "
            "set or rotate it; leave blank to keep the existing "
            "password unchanged."
        ),
        'keys': [
            {'key': 'MAIL_SERVER', 'type': 'str',
             'default': 'smtp.example.com',
             'hint': 'SMTP host (e.g. smtp.gmail.com, mail.example.com).'},
            {'key': 'MAIL_PORT', 'type': 'int', 'default': 587,
             'hint': 'Common: 25 plain, 465 direct SSL, 587 STARTTLS.'},
            {'key': 'MAIL_USE_TLS', 'type': 'bool', 'default': True,
             'hint': 'STARTTLS upgrade — pair with port 587.'},
            {'key': 'MAIL_USE_SSL', 'type': 'bool', 'default': False,
             'hint': 'Direct SSL on connect — pair with port 465.'},
            {'key': 'MAIL_USERNAME', 'type': 'str', 'default': '',
             'hint': 'SMTP login (often the same as the From address).'},
            {'key': 'MAIL_PASSWORD', 'type': 'str', 'default': '',
             'hint': 'SMTP password. Leave blank to keep the current '
                     'value (it is never pre-filled into the form).'},
            {'key': 'MAIL_SENDER', 'type': 'str',
             'default': 'cmdbsyncer@example.com',
             'hint': 'Default From: header.'},
            {'key': 'MAIL_SUBJECT_PREFIX', 'type': 'str',
             'default': '[CMDBsyncer]',
             'hint': 'Prefix prepended to every outgoing subject line.'},
        ],
    },
    {
        'ident': 'sentry',
        'name': 'Sentry / Debug',
        'description': (
            "Forward unhandled exceptions to a Sentry instance and "
            "toggle the global Flask DEBUG flag. The full ``LOGGING`` "
            "dict (handlers, formatters, syslog targets, …) is a "
            "nested structure and stays in BaseConfig — override it in "
            "local_config.py by hand."
        ),
        'note': "All three keys take effect only after a service restart.",
        'keys': [
            {'key': 'DEBUG', 'type': 'bool', 'default': False,
             'hint': "Enables Flask debug mode plus the 'debug' "
                     "logger at DEBUG level. Off in production."},
            {'key': 'SENTRY_ENABLED', 'type': 'bool', 'default': True,
             'hint': 'Toggle the Sentry integration on/off.'},
            {'key': 'SENTRY_DSN', 'type': 'str',
             'default': 'https://<key>@sentry.example.com/<project>',
             'hint': 'Project DSN from your Sentry project settings.'},
        ],
    },
    {
        'ident': 'cmk',
        'name': 'Checkmk options',
        'description': (
            "Tunables for the Checkmk plugin — bulk-API batching, "
            "name normalisation, log verbosity, and the safety flags "
            "that govern host/tag deletion."
        ),
        'keys': [
            {'key': 'CMK_BULK_CREATE_HOSTS', 'type': 'bool', 'default': True,
             'hint': 'Use the Checkmk REST bulk-create endpoint.'},
            {'key': 'CMK_BULK_CREATE_OPERATIONS', 'type': 'int',
             'default': 300, 'hint': 'Hosts per bulk-create batch.'},
            {'key': 'CMK_BULK_UPDATE_HOSTS', 'type': 'bool', 'default': True,
             'hint': 'Use bulk-update for label changes.'},
            {'key': 'CMK_BULK_UPDATE_OPERATIONS', 'type': 'int',
             'default': 50, 'hint': 'Hosts per bulk-update batch.'},
            {'key': 'CMK_BULK_DELETE_HOSTS', 'type': 'bool', 'default': True,
             'hint': 'Use bulk-delete.'},
            {'key': 'CMK_BULK_DELETE_OPERATIONS', 'type': 'int',
             'default': 50, 'hint': 'Hosts per bulk-delete batch.'},
            {'key': 'CMK_DONT_DELETE_HOSTS', 'type': 'bool', 'default': False,
             'hint': 'Safety: never delete hosts in Checkmk, '
                     'regardless of rules.'},
            {'key': 'CMK_DONT_DELETE_TAGS', 'type': 'bool', 'default': True,
             'hint': 'Safety: never delete host-tag groups in Checkmk.'},
            {'key': 'CMK_LOWERCASE_FOLDERNAMES', 'type': 'bool',
             'default': True,
             'hint': 'Normalise Checkmk folder names to lowercase.'},
            {'key': 'CMK_LOWERCASE_LABEL_VALUES', 'type': 'bool',
             'default': False,
             'hint': 'Normalise Checkmk label values to lowercase.'},
            {'key': 'CMK_DETAILED_LOG', 'type': 'bool', 'default': False,
             'hint': 'Verbose per-host log output during sync.'},
            {'key': 'CMK_GET_HOST_BY_FOLDER', 'type': 'bool',
             'default': False,
             'hint': 'Iterate hosts via folder traversal — use for '
                     'very large Checkmk instances.'},
            {'key': 'CMK_WRITE_STATUS_BACK', 'type': 'bool', 'default': False,
             'hint': 'Update existing hosts in Checkmk on every sync pass.'},
        ],
    },
    {
        'ident': 'session',
        'name': 'Session / Reverse Proxy',
        'description': (
            "HTTPS gating, session-cookie hardening, login rate limit "
            "and reverse-proxy trust. Configure these once when wiring "
            "the Syncer behind nginx/Apache."
        ),
        'note': (
            "Set ``TRUSTED_PROXIES`` to the number of reverse-proxy hops "
            "(usually ``1``) so ``X-Forwarded-Proto`` is honored. Then "
            "``SESSION_COOKIE_SECURE`` and the API HTTPS gate work "
            "correctly. ``ALLOW_INSECURE_API_AUTH`` is for dev only."
        ),
        'keys': [
            {'key': 'TRUSTED_PROXIES', 'type': 'int', 'default': 1,
             'hint': 'Reverse-proxy hops between client and app. '
                     '0 = no proxy, 1 = one (typical), 2 = e.g. CDN+nginx.'},
            {'key': 'REQUIRE_HTTPS', 'type': 'bool', 'default': True,
             'hint': 'Enforce HTTPS for the admin GUI (default). Keeps '
                     'SESSION_COOKIE_SECURE on and shows a banner on '
                     'plain HTTP. Set to False only to allow HTTP-only '
                     'mode intentionally.'},
            {'key': 'SESSION_COOKIE_SECURE', 'type': 'bool', 'default': True,
             'hint': 'Set the Secure flag on the session cookie. '
                     'Auto-disabled at startup when REQUIRE_HTTPS=False.'},
            {'key': 'SESSION_COOKIE_NAME', 'type': 'str', 'default': 'syncer',
             'hint': 'Cookie name. Change to avoid collisions when '
                     'multiple syncers share a hostname.'},
            {'key': 'ADMIN_SESSION_HOURS', 'type': 'int', 'default': 2,
             'hint': 'Session TTL after login.'},
            {'key': 'AUTH_RATE_LIMIT', 'type': 'str',
             'default': '3 per minute; 10 per hour',
             'hint': 'Per-IP rate limit for login + password-reset POSTs '
                     '(Flask-Limiter syntax).'},
            {'key': 'RATELIMIT_STORAGE_URI', 'type': 'str',
             'default': 'memory://',
             'hint': 'Backend for rate-limit counters. Use redis:// or '
                     'mongodb:// for multi-worker deployments.'},
            {'key': 'ALLOW_INSECURE_API_AUTH', 'type': 'bool',
             'default': False,
             'hint': 'Dev-only: allow Basic Auth over plain HTTP. '
                     'Never enable in production.'},
            {'key': 'BASE_PREFIX', 'type': 'str', 'default': '/',
             'hint': 'URL prefix the app is mounted under. Change when '
                     'the reverse proxy serves the syncer at a sub-path.'},
        ],
    },
    {
        'ident': 'password_policy',
        'name': 'Password policy',
        'description': (
            "Minimum length and character-class requirements enforced "
            "on local user-account passwords."
        ),
        'note': (
            "``PASSWD_SPECIAL_NEEDED`` controls how many of the four "
            "character-class flags above must hold for a password to "
            "be accepted (default 3 of 4)."
        ),
        'keys': [
            {'key': 'PASSWD_MIN_PASSWD_LENGTH', 'type': 'int', 'default': 9,
             'hint': 'Minimum character count.'},
            {'key': 'PASSWD_SPECIAL_CHARS', 'type': 'bool', 'default': True,
             'hint': 'Require at least one special character.'},
            {'key': 'PASSWD_SPECIAL_DIGITS', 'type': 'bool', 'default': True,
             'hint': 'Require at least one digit.'},
            {'key': 'PASSWD_SEPCIAL_UPPER', 'type': 'bool', 'default': True,
             'hint': 'Require at least one upper-case letter. (Note: '
                     'historic spelling, kept for backward compat.)'},
            {'key': 'PASSWD_SEPCIAL_LOWER', 'type': 'bool', 'default': True,
             'hint': 'Require at least one lower-case letter.'},
            {'key': 'PASSWD_SPECIAL_NEEDED', 'type': 'int', 'default': 3,
             'hint': 'How many of the four character-class flags above '
                     'must hold (max 4).'},
        ],
    },
    {
        'ident': 'http_client',
        'name': 'HTTP client',
        'description': (
            "Outbound HTTP behaviour the Syncer's plugins use when "
            "talking to Checkmk, Netbox, Jira and the like — request "
            "timeout, retry policy, TLS-error tolerance, and the "
            "process timeout for spawned helpers."
        ),
        'keys': [
            {'key': 'HTTP_REQUEST_TIMEOUT', 'type': 'int', 'default': 30,
             'hint': 'Per-request timeout in seconds.'},
            {'key': 'HTTP_REPEAT_TIMEOUT', 'type': 'int', 'default': 3,
             'hint': 'Sleep between retries, in seconds.'},
            {'key': 'HTTP_MAX_RETRIES', 'type': 'int', 'default': 2,
             'hint': 'Number of automatic retries on transient errors.'},
            {'key': 'DISABLE_SSL_ERRORS', 'type': 'bool', 'default': False,
             'hint': 'Skip TLS certificate verification on outbound '
                     'calls. Dev / lab only.'},
            {'key': 'PROCESS_TIMEOUT', 'type': 'int', 'default': 15,
             'hint': 'Timeout for subprocesses spawned during sync.'},
        ],
    },
    {
        'ident': 'data_normalisation',
        'name': 'Data normalisation',
        'description': (
            "Cleanup applied to imported host names, labels and "
            "attributes before they are stored or pushed back out."
        ),
        'note': (
            "``REPLACE_ATTRIBUTE_KEYS`` runs the configured ``REPLACERS`` "
            "table over attribute keys (umlauts → ASCII, spaces → "
            "underscore, …). The table itself is a list of pairs and "
            "must stay in ``local_config.py`` on disk — only the "
            "boolean toggle is editable here."
        ),
        'keys': [
            {'key': 'LOWERCASE_HOSTNAMES', 'type': 'bool', 'default': False,
             'hint': 'Lowercase every imported hostname.'},
            {'key': 'LOWERCASE_ATTRIBUTE_KEYS', 'type': 'bool',
             'default': False,
             'hint': 'Lowercase every imported attribute key.'},
            {'key': 'REPLACE_ATTRIBUTE_KEYS', 'type': 'bool', 'default': False,
             'hint': 'Apply the REPLACERS table to attribute keys.'},
            {'key': 'CHECK_FOR_VALID_HOSTNAME', 'type': 'bool',
             'default': True,
             'hint': 'Reject hostnames that fail the RFC-1123 regex.'},
            {'key': 'LABELS_ITERATE_FIRST_LEVEL', 'type': 'bool',
             'default': False,
             'hint': 'Treat the first-level keys of nested label dicts '
                     'as individual labels.'},
            {'key': 'LABELS_IMPORT_EMPTY', 'type': 'bool', 'default': False,
             'hint': 'Import labels even when their value is empty.'},
        ],
    },
    {
        'ident': 'ldap',
        'name': 'LDAP login',
        'description': (
            "Enterprise LDAP/AD login. When enabled, the login view "
            "tries an LDAP bind before falling back to the local "
            "password. Pick **direct-bind** (set "
            "``LDAP_USER_DN_TEMPLATE``) or **search-bind** (set "
            "``LDAP_BIND_USER`` + ``LDAP_BIND_PASSWORD`` + "
            "``LDAP_SEARCH_BASE``). ``LDAP_ROLE_MAPPING`` is a nested "
            "dict and stays in ``local_config.py`` on disk."
        ),
        'note': (
            "``LDAP_BIND_PASSWORD`` is on the protected list — its "
            "current value is never echoed back. Type a new value to "
            "set or rotate it; leave blank to keep the existing "
            "password unchanged."
        ),
        'keys': [
            {'key': 'LDAP_LOGIN', 'type': 'bool', 'default': True,
             'hint': 'Master toggle. Off = LDAP path is skipped, local '
                     'passwords only.'},
            {'key': 'LDAP_SERVER', 'type': 'str',
             'default': 'ldaps://ldap.example.com',
             'hint': 'LDAP URL. Prefer ldaps:// for TLS.'},
            {'key': 'LDAP_USER_DN_TEMPLATE', 'type': 'str',
             'default': 'uid={username},ou=people,dc=example,dc=com',
             'hint': 'Direct-bind template with {username}. Leave empty '
                     'to use search-bind mode below instead.'},
            {'key': 'LDAP_BIND_USER', 'type': 'str',
             'default': 'cn=syncer,ou=services,dc=example,dc=com',
             'hint': 'Search-bind: service-account DN. Required when '
                     'LDAP_USER_DN_TEMPLATE is empty.'},
            {'key': 'LDAP_BIND_PASSWORD', 'type': 'str', 'default': '',
             'hint': 'Search-bind: service-account password. Leave '
                     'blank to keep the current value.'},
            {'key': 'LDAP_SEARCH_BASE', 'type': 'str',
             'default': 'ou=people,dc=example,dc=com',
             'hint': 'Search-bind: base DN to look up users under.'},
            {'key': 'LDAP_SEARCH_FILTER', 'type': 'str',
             'default': '(mail={email})',
             'hint': 'Filter with {email} or {username}.'},
            {'key': 'LDAP_REQUIRED_GROUP', 'type': 'str', 'default': '',
             'hint': 'Optional: require this group DN in the user’s '
                     'memberOf attribute. Empty = any bind succeeds.'},
            {'key': 'LDAP_NAME_ATTR', 'type': 'str', 'default': 'cn',
             'hint': 'LDAP attribute used for User.name on auto-create.'},
            {'key': 'LDAP_AUTO_CREATE', 'type': 'bool', 'default': True,
             'hint': 'Create a local User record on first successful '
                     'LDAP login.'},
        ],
    },
    {
        'ident': 'ui_branding',
        'name': 'UI / Branding',
        'description': (
            "Cosmetic + UX knobs — admin-page sizes, the navigation "
            "colour palette, an optional banner above every admin "
            "page, plus the timestamp format."
        ),
        'keys': [
            {'key': 'STYLE_NAV_BACKGROUND_COLOR', 'type': 'str',
             'default': '#000',
             'hint': 'Background colour of the top navigation bar '
                     '(hex, rgb(), CSS colour name).'},
            {'key': 'STYLE_NAV_LINK_COLOR', 'type': 'str',
             'default': '#fff',
             'hint': 'Link colour inside the top navigation bar.'},
            {'key': 'HEADER_HINT', 'type': 'str', 'default': '',
             'hint': 'Optional banner shown above every admin page. '
                     'Useful for "PRE-PROD — do not touch" warnings.'},
            {'key': 'TIME_STAMP_FORMAT', 'type': 'str',
             'default': '%d.%m.%Y %H:%M',
             'hint': 'strftime format for timestamps in the admin UI.'},
            {'key': 'HOST_PAGESIZE', 'type': 'int', 'default': 100,
             'hint': 'Hosts shown per page in the admin host list.'},
            {'key': 'HOST_LOG_LENGTH', 'type': 'int', 'default': 30,
             'hint': 'Number of log lines kept on the host detail view.'},
            {'key': 'LABEL_PREVIEW_DISABLED', 'type': 'bool',
             'default': False,
             'hint': 'Hide the live label preview on rule edit pages '
                     '(useful for very large rule sets).'},
            {'key': 'SWAGGER_ENABLED', 'type': 'bool', 'default': True,
             'hint': 'Expose the interactive ``/api/v1`` Swagger UI. '
                     'Turn off in hardened deployments.'},
        ],
    },
]


def get_preset(ident):
    """Return the preset with this ``ident`` or ``None``."""
    for preset in PRESETS:
        if preset['ident'] == ident:
            return preset
    return None
