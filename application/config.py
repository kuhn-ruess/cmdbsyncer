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
    SESSION_COOKIE_NAME = "syncer"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'

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
                "address": ["127.0.0.1", 514],
                #"address": "/dev/log",
                "facility": "local6",
                "formatter": "syslog"
                }
        },
        "loggers": {
            "debug": {
                "handlers": ["console"],
                "level": 100,
                "propagate": "True"
            },
            "syslog": {
                "handlers": ["syslog"],
                "level": "INFO",
                "propagate": "True"
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
    CHECK_FOR_VALID_HOSTNAME = True
    LABELS_ITERATE_FIRST_LEVEL = False
    LABELS_IMPORT_EMPTY = False

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

    SWAGGER_ENABLED = True
    DEBUG = False
    ADVANCED_RULE_DEBUG = False

    CMDB_MODE = False

    MONGODB_SETTINGS = _get_mongo_settings('127.0.0.1')

    CMDB_MODELS = {
        'host': {
            #'ipaddress' : {"type": "string"},
        },
        'all': {
            #'notification': {"type": "boolean"},

        }

    }

    HOST_PAGESIZE = 100
    LABEL_PREVIEW_DISABLED = False

    REMOTE_USER_LOGIN = False

    # Rate limit for login and password-reset request (Flask-Limiter syntax).
    # Applied per client IP to the POST handler; GET (rendering the form) is
    # not rate-limited.
    AUTH_RATE_LIMIT = '3 per minute; 10 per hour'
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
