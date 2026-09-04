""" Config File """
# pylint: disable=too-few-public-methods  # plain Flask config classes
import os

def _get_mongo_settings(default_host):
    return {
        'db': os.environ.get('CMDBSYNCER_MONGODB_DB', 'cmdb-api'),
        'host': os.environ.get('CMDBSYNCER_MONGODB_HOST', default_host),
        'port': int(os.environ.get('CMDBSYNCER_MONGODB_PORT', '27017')),
        'alias': os.environ.get('CMDBSYNCER_MONGODB_ALIAS', 'default'),
    }

class BaseConfig():
    """
    Generel System white Configuration.
    Can be overwritten later if needed.
    """
    SECRET_KEY = None # To be overwritten in local_conifg.py
    CRYPTOGRAPHY_KEY = None # To be overwritten in local_config.py
    TIME_STAMP_FORMAT = "%d.%m.%Y %H:%M"
    HOST_LOG_LENGTH = 30
    ADMIN_SESSION_HOURS = 2
    BASE_PREFIX = '/'

    # Admin pages use the full window width instead of Bootstrap's
    # 1140px container — the host and object lists carry wide columns
    # (labels, CMDB attributes) and the forms edit long values, both of
    # which were squeezed while the screen stayed empty left and right.
    FLASK_ADMIN_FLUID_LAYOUT = True
    SESSION_COOKIE_NAME = "syncer"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Master switch for the GUI HTTPS enforcement.
    # True (default): keep SESSION_COOKIE_SECURE = True. A yellow banner
    #   is rendered on every admin/login page over plain HTTP, telling
    #   the admin to either configure TLS (and a trusted proxy if
    #   applicable) or to acknowledge HTTP-only mode by flipping this
    #   switch off.
    # False: SESSION_COOKIE_SECURE is forced to False at startup so
    #   plain-HTTP logins still work, and the banner is suppressed —
    #   set this once you have intentionally chosen HTTP-only.
    # Does NOT affect the separate API HTTPS gate
    # (see ALLOW_INSECURE_API_AUTH).
    REQUIRE_HTTPS = True

    # Quick shortcut to raise/lower the log level without replacing the
    # whole LOGGING dict below. Accepts a level name ("DEBUG", "INFO", …)
    # or a numeric level and is applied to both loggers after dictConfig.
    # None leaves the levels from LOGGING untouched.
    LOG_LEVEL = None

    # Both loggers below receive every entry the central Log() module
    # writes (see application/modules/log/log.py):
    #   debug  — human/console output, muted by default (level 100),
    #            switched on per run with `--debug` or via LOG_LEVEL.
    #   syslog — the external sink. Point its handler wherever your log
    #            pipeline lives (syslog, file, …). It does not propagate,
    #            so the external copy never doubles up on the console.
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": "False",
        "formatters": {
            "verbose": {
                "format": "%(levelname)s - %(message)s"
            },
            "syslog": {
                "format": "%(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class":"logging.StreamHandler",
                "formatter": "verbose"
            },
            "syslog": {
                "class": "logging.handlers.SysLogHandler",
                # Tuple, not list — socket.sendto() rejects a list.
                "address": ("127.0.0.1", 514),
                #"address": "/dev/log",
                "facility": "local6",
                "formatter": "syslog"
                }
        },
        "loggers": {
            "debug": {
                "handlers": ["console"],
                "level": 100,
                "propagate": True
            },
            "syslog": {
                "handlers": ["syslog"],
                "level": "INFO",
                "propagate": False
            }
        }
    }

    # Minimum length for user Passwords (not applied to admin panel)
    PASSWD_MIN_PASSWD_LENGTH = 9
    # Password needs special signs
    PASSWD_SPECIAL_CHARS = True
    # Password need numbers
    PASSWD_SPECIAL_DIGITS = True
    # There must be uppercase letters
    PASSWD_SEPCIAL_UPPER = True
    # There musst lowercase letters
    PASSWD_SEPCIAL_LOWER = True
    # How many of the PASSWD_SEPCIAL prefixt  options must apply
    PASSWD_SPECIAL_NEEDED = 3
    SENTRY_ENABLED = False
    SENTRY_DSN = ""

    BOOTSTRAP_SERVE_LOCAL = True

    STYLE_NAV_BACKGROUND_COLOR = "#000"
    STYLE_NAV_LINK_COLOR = "#fff"
    HEADER_HINT = ""



    REPLACE_ATTRIBUTE_KEYS = False
    LOWERCASE_ATTRIBUTE_KEYS = False
    LOWERCASE_HOSTNAMES = False
    LABELS_ITERATE_FIRST_LEVEL = False
    LABELS_IMPORT_EMPTY = False

    # Label history behind the host "Timeline" tab. Off by default: it
    # writes a document on every host save that changes labels, so an
    # import that rewrites labels on every run turns it into the biggest
    # collection in the database. Enable it where the history is worth
    # that write volume. Retention is enforced by a TTL index; run
    # `sys self_configure` after changing the number of days.
    LABEL_HISTORY_ENABLED = False
    LABEL_HISTORY_RETENTION_DAYS = 90

    # Retention of the collections that grow with every run. All are
    # enforced by MongoDB itself through a TTL index; run
    # `sys self_configure` after changing one.
    ANSIBLE_RUN_STATS_RETENTION_DAYS = 90
    FIELD_APPROVAL_RETENTION_DAYS = 365
    AUDIT_RETENTION_DAYS = 365
    APPROVAL_RETENTION_DAYS = 365

    # Emit an audit event for label changes made by an import. Off by
    # default: an import that rewrites labels on every run produces one
    # event per host per run and buries the changes a person made.
    AUDIT_IMPORT_LABEL_CHANGES = False

    REPLACERS = [
      (' ', '_'),
      ('/', '_'),
      (',', '-'),
      ('&', '-'),
      ('(', '-'),
      (')', '-'),
      ('ü', 'ue'),
      ('ä', 'ae'),
      ('ö', 'oe'),
      ('ß', 'ss'),
      ('Ü', 'UE'),
      ('Ä', 'AE'),
      ('Ö', 'OE'),
    ]


    DISABLE_SSL_ERRORS = False
    HTTP_REQUEST_TIMEOUT = 30

    HTTP_REPEAT_TIMEOUT = 3
    HTTP_MAX_RETRIES = 2
    # Checkmk's activate-changes wait-for-completion is a redirect-based
    # long-poll; raise this if a big activation still hits "Exceeded N redirects".
    HTTP_MAX_REDIRECTS = 100

    SWAGGER_ENABLED = True
    DEBUG = False
    ADVANCED_RULE_DEBUG = False

    CMDB_MODE = False

    MONGODB_SETTINGS = _get_mongo_settings('127.0.0.1')

    CMDB_MODELS = {
        'host': {
            #'ipaddress' : {"type": "string"},
        },
        # First-class CI types — opinionated default fields that an
        # operator typically wants on a Service / Application /
        # Location entry. Override or extend in local_config.py to
        # match your environment; the keys here only define what
        # appears empty on a fresh CI.
        'service': {
            'owner':       {'type': 'string'},
            'criticality': {'type': 'string'},
            'sla':         {'type': 'string'},
            'description': {'type': 'string'},
        },
        'application': {
            'owner':       {'type': 'string'},
            'criticality': {'type': 'string'},
            'repo_url':    {'type': 'string'},
            'description': {'type': 'string'},
        },
        'location': {
            'address':     {'type': 'string'},
            'city':        {'type': 'string'},
            'country':     {'type': 'string'},
            'room':        {'type': 'string'},
        },
        'all': {
            #'notification': {"type": "boolean"},

        }

    }

    # Labels listed here go through a four-eyes approval queue: any
    # change to one of these labels in the UI is held back until a user
    # with the 'approval' role accepts it. The 'approval_bypass' role
    # opts a user out of the queue entirely (normal behavior, edit
    # lands immediately). Empty list disables the workflow.
    APPROVAL_REQUIRED_LABELS = []

    HOST_PAGESIZE = 100
    LABEL_PREVIEW_DISABLED = False

    # The "Messages" card on the start page, fed from the .txt files in
    # ``application/notices/``. Off by default — the notices are release
    # announcements, and once they have been read they are only in the way.
    # Turn it back on when a release has something that has to be seen.
    START_PAGE_NOTICES_ENABLED = False

    REMOTE_USER_LOGIN = False

    # Verbose login-flow logging. Off by default — flip on temporarily to
    # diagnose why an LDAP / remote_user login is rejected. When True, the
    # auth code (OSS dispatcher + Enterprise LDAP / remote_user hooks)
    # writes structured entries to the Settings -> Log view at every
    # decision point: bind mode chosen, search filter, group membership,
    # auto-create vs lookup, role mapping. No password is ever logged.
    AUTH_DEBUG = False

    # Rate limit for login and password-reset request (Flask-Limiter syntax).
    # Applied per client IP to the POST handler; GET (rendering the form) is
    # not rate-limited.
    AUTH_RATE_LIMIT = '3 per minute; 10 per hour'
    # Rate limit for the /api/v1 namespace. Only 401 responses deduct from
    # the bucket (see application/api/views.py), so legitimate polling
    # never spends quota. Picked generous enough that a misconfigured
    # monitoring agent producing repeated 401s does not lock out the whole
    # API for the rest of the hour, while still throttling credential
    # stuffing. Set tighter via local_config.py if your network is fully
    # trusted, or looser if you have many polling clients.
    API_RATE_LIMIT = '30 per minute; 300 per hour'
    # Flask-Limiter storage backend. Default is in-process memory, which is
    # fine for single-worker deployments. For multiple workers, set to
    # e.g. 'redis://localhost:6379' or 'mongodb://localhost:27017/cmdb-api'.
    RATELIMIT_STORAGE_URI = 'memory://'
    # Development-only escape hatch for local API testing over plain HTTP.
    # Keep disabled in normal deployments because password-based API auth
    # should require TLS or a trusted reverse proxy.
    ALLOW_INSECURE_API_AUTH = False

    # Number of trusted reverse-proxy hops between the client and the app.
    # 0 (default) = no proxy, do NOT trust X-Forwarded-* headers.
    #     Correct for mod_wsgi and direct deployments.
    # 1 = one proxy hop (e.g. Apache/nginx in front of a Docker container).
    #     Apache/nginx must set X-Forwarded-Proto correctly and the app
    #     must only be reachable via the proxy.
    # 2 = two hops (e.g. Cloudflare → nginx → app).
    # When > 0, werkzeug.middleware.proxy_fix.ProxyFix rewrites
    # request.scheme / request.remote_addr / request.host from the
    # X-Forwarded-* headers of that depth.
    TRUSTED_PROXIES = 0

    # LDAP login (enterprise feature)
    # If LDAP_LOGIN is enabled and the enterprise 'ldap_login' hook is registered,
    # the login view will attempt an LDAP bind before falling back to local passwords.
    LDAP_LOGIN = False
    LDAP_SERVER = ''
    # Direct-bind mode: format string with {username} placeholder, e.g.
    #   'uid={username},ou=people,dc=example,dc=com'
    # Leave empty to use search-based mode (requires LDAP_BIND_USER).
    LDAP_USER_DN_TEMPLATE = ''
    # Search-based mode: bind with a service account, locate the user via filter,
    # then re-bind as that user to verify the password.
    LDAP_BIND_USER = ''
    LDAP_BIND_PASSWORD = ''
    LDAP_SEARCH_BASE = ''
    LDAP_SEARCH_FILTER = '(mail={email})'
    # If set, the bound user must have this group DN in their `memberOf`
    # attribute. Leave empty to allow any successfully bound user.
    LDAP_REQUIRED_GROUP = ''
    # LDAP attribute used for User.name on auto-create.
    LDAP_NAME_ATTR = 'cn'
    # Create a local User record on first successful LDAP login.
    LDAP_AUTO_CREATE = True
    # Map LDAP group DNs to roles. When non-empty, roles/global_admin are
    # recomputed from group memberships on every login (LDAP is the source
    # of truth). When empty, user roles are left untouched.
    #   {
    #     'cn=admins,ou=groups,dc=example,dc=com': {'global_admin': True},
    #     'cn=ops,ou=groups,dc=example,dc=com':    {'roles': ['host', 'log']},
    #   }
    LDAP_ROLE_MAPPING = {}


    # OIDC / SSO login (enterprise feature)
    # Native OpenID Connect client — logs users in against Entra ID,
    # Okta, Keycloak, Google Workspace, Auth0 or any OIDC-compliant IdP
    # without a mod_auth_openidc proxy in front. When OIDC_LOGIN is
    # enabled and the enterprise 'oidc_login' feature is registered, the
    # login page shows a "Sign in with SSO" button pointing at
    # /oidc/login, and /oidc/callback handles the IdP redirect.
    # All of the keys below are editable from Settings -> Config ->
    # local_config.py, "OIDC / SSO login" preset.
    OIDC_LOGIN = False
    # Name of the Account (type 'oidc_idp') holding the connection:
    #   address = issuer URL, username = client id, password = client secret.
    # Credentials live on the Account so external secret stores apply.
    OIDC_ACCOUNT = ''
    # Scopes requested from the IdP. A plain string is split on commas
    # and whitespace, so the config editor can set it too.
    OIDC_SCOPES = 'openid email profile'
    # Claims the user record is built from.
    OIDC_EMAIL_CLAIM = 'email'
    OIDC_NAME_CLAIM = 'name'
    OIDC_GROUPS_CLAIM = 'groups'
    # If set, the user must carry this group in their groups claim.
    OIDC_REQUIRED_GROUP = ''
    # Create a local User record on first successful OIDC login.
    OIDC_AUTO_CREATE = True
    # Shortcut for the common case: members of this group become global
    # admins. Merged into OIDC_ROLE_MAPPING below, so both can be used.
    OIDC_ADMIN_GROUP = ''
    # Roles every user passing the gate receives. String (comma or
    # whitespace separated) or list, so the config editor can set it.
    OIDC_DEFAULT_ROLES = ''
    # Map IdP groups to roles. When non-empty (or OIDC_ADMIN_GROUP /
    # OIDC_DEFAULT_ROLES are set), roles/api_roles/global_admin are
    # recomputed from group memberships on every login (the IdP is the
    # source of truth). When all three are empty, roles are untouched.
    #   {
    #     'cmdbsyncer-admins': {'global_admin': True},
    #     'cmdbsyncer-ops':    {'roles': ['host', 'log']},
    #     'cmdbsyncer-api':    {'api_roles': ['all']},
    #   }
    OIDC_ROLE_MAPPING = {}


    FILEADMIN_PATH = os.environ.get('CMDBSYNCER_FILEADMIN_PATH', '/var/cmdbsyncer/files')

    ### Checkmk Stuff

    CMK_WRITE_STATUS_BACK = False # Syncer updates if Host existing in checkmk

    CMK_BULK_CREATE_HOSTS = True
    CMK_BULK_CREATE_OPERATIONS = 300


    CMK_DONT_DELETE_HOSTS = False
    CMK_BULK_DELETE_HOSTS = True
    CMK_BULK_DELETE_OPERATIONS = 50

    CMK_DONT_DELETE_TAGS = True

    CMK_BULK_UPDATE_HOSTS = True
    CMK_BULK_UPDATE_OPERATIONS = 50

    CMK_LOWERCASE_FOLDERNAMES = True
    CMK_LOWERCASE_LABEL_VALUES = False

    # If set, the Syncer will first calculate everhting,
    # and then send bulk operations finally.
    # This should prevent db timeouts for slow cmk operations.
    # but needs more RAM.
    CMK_COLLECT_BULK_OPERATIONS = False

    # Checkmk API will break for get_hosts at some point
    # In the example it was at 50k hosts.
    # Activating this, Syncer will query Hosts Folder by Folder.
    # That will take longer, but will not break Checkmk.
    CMK_GET_HOST_BY_FOLDER = False

    # Log all Changed done on Hosts
    CMK_DETAILED_LOG = False

    CMK_JINJA_USE_REPLACERS = False
    CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES = False

    NETBOX_IMPORT_NESTED = False

    # Structured (JSON) log stream. Needs a license carrying the
    # feature; without one these are inert. One switch per thing that
    # logs, and neither needs the other: wanting the imports in the
    # collector says nothing about wanting the web log there too.
    # The web application and its workers:
    JSON_LOGGING_ENABLED = False
    # `cmdbsyncer <command>` runs — imports, exports, cron. A run
    # printing to a terminal stays plain text, unless the records go to
    # a file.
    JSON_LOGGING_CLI = False
    # A path here takes the records instead of the stream: for runs
    # whose output nobody collects — started from outside the container,
    # for instance — the file is where a collector can still find them.
    JSON_LOGGING_FILE = ''
    JSON_LOGGING_STREAM = 'stdout'
    JSON_LOGGING_LEVEL = 'INFO'

    PROCESS_TIMEOUT = 15

    # Email / SMTP (used for password-reset mails and other notifications).
    # Flask-Mail picks up MAIL_SERVER/MAIL_PORT/MAIL_USE_TLS/MAIL_USE_SSL/
    # MAIL_USERNAME/MAIL_PASSWORD directly; MAIL_SENDER and
    # MAIL_SUBJECT_PREFIX are read by application/modules/email.py.
    MAIL_SERVER = 'localhost'
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_SENDER = 'cmdbsyncer@localhost'
    MAIL_SUBJECT_PREFIX = '[CMDBsyncer]'

class ProductionConfig(BaseConfig):
    """
    Production Configuration.
    """
    DEBUG = False

class ComposeConfig(BaseConfig):
    """
    Config to run in docker_compose
    """
    DEBUG = False
    MONGODB_SETTINGS = _get_mongo_settings('mongo')
