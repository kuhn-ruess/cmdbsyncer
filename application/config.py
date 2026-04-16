""" Config File """
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
