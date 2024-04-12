""" Config File """
#pylint: disable=too-few-public-methods
import logging

class BaseConfig():
    """
    Generel System white Configuration.
    Can be overwritten later if needed.
    """
    SECRET_KEY = "j+}[56_c$%u5F5PH)P4s~q(.H'mZH!dFkn?e!@{,f)Zj9Cd<Dj@DG"
    TIME_STAMP_FORMAT = "%d.%m.%Y %H:%M"
    HOST_LOG_LENGTH = 30
    ADMIN_SESSION_HOURS = 2
    BASE_PREFIX = '/'

    LOG_LEVEL = logging.INFO
    LOG_CHANNEL = logging.StreamHandler()

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

    REPLACERS = [
      (' ', '_'),
      (',', ''),
      ('/', '-'),
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
    SWAGGER_ENABLED = True
    DEBUG = True
    MONGODB_SETTINGS = {
        'db': 'cmdb-api',
        'host': '127.0.0.1',
        'port': 27017,
        'alias': 'default',

    }

    FILEADMIN_PATH = '/srv/cmdbsyncer-files'

    CMK_22_23_HANDLE_TAG_LABEL_BUG = False

    CMK_BULK_CREATE_HOSTS = True
    CMK_BULK_CREATE_OPERATIONS = 300

    CMK_BULK_DELETE_HOSTS = False
    CMK_BULK_DELETE_OPERATIONS = 100

    CMK_BULK_UPDATE_HOSTS = False # So no ETag Checking
    CMK_BULK_UPDATE_OPERATIONS = 10

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
