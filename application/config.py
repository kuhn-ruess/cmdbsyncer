""" Config File """
#pylint: disable=too-few-public-methods

class BaseConfig():
    """
    Generel System white Configuration.
    Can be overwritten later if needed.
    """
    SECRET_KEY = "[1dmBlwnsY788wI3x<[R34qlUF2Xc/>2o7grl{L9C9Yj)8£/O3/2l="
    CRYPTOGRAPHY_KEY = b'nto4ioGgQDlJ-r5jqvyEtTpUQC2fkOAG4Df-E8OlVm8='

    TIME_STAMP_FORMAT = "%d.%m.%Y %H:%M"
    HOST_LOG_LENGTH = 30
    ADMIN_SESSION_HOURS = 2
    BASE_PREFIX = '/'
    SESSION_COOKIE_NAME = "syncer"

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


    DISABLE_SSL_ERRORS = True
    HTTP_REQUEST_TIMEOUT = 30

    HTTP_REPEAT_TIMEOUT = 3
    HTTP_MAX_RETRIES = 2

    SWAGGER_ENABLED = True
    DEBUG = True
    ADVANCED_RULE_DEBUG = False

    MONGODB_SETTINGS = {
        'db': 'cmdb-api',
        'host': '127.0.0.1',
        'port': 27017,
        'alias': 'default',

    }


    FILEADMIN_PATH = '/srv/cmdbsyncer-files'

    ### Checkmk Stuff

    CMK_BULK_CREATE_HOSTS = True
    CMK_BULK_CREATE_OPERATIONS = 300


    CMK_DONT_DELETE_HOSTS = False
    CMK_BULK_DELETE_HOSTS = True
    CMK_BULK_DELETE_OPERATIONS = 50

    CMK_DONT_DELETE_TAGS = True

    CMK_BULK_UPDATE_HOSTS = True
    CMK_BULK_UPDATE_OPERATIONS = 50

    CMK_LOWERCASE_FOLDERNAMES = True

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
    MONGODB_SETTINGS = {
        'db': 'cmdb-api',
        'host': 'mongo',
        'port': 27017,
        'alias': 'default',
    }
