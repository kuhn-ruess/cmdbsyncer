""" Config File """
#pylint: disable=too-few-public-methods
import datetime
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


    REPLACE_ATTRIBUTE_KEYS = False
    LOWERCASE_ATTRIBUTE_KEYS = False
    LOWERCASE_HOSTNAMES = False

    REPLACERS = [
      (' ', '_'),
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
    SWAGGER_ENABLED = True
    DEBUG = True
    MONGODB_SETTINGS = {
        'db': 'cmdb-api',
        'host': '127.0.0.1',
        'port': 27017,
        'alias': 'default',

    }

    TIMEZONE = datetime.timezone.utc

    FILEADMIN_PATH = '/srv/cmdbsyncer-files'

    ### Checkmk Stuff

    #Checkmk has a bug:
    # Bad Request These fields have problems: entries{'entries': {'0': {'attributes': {'labels': ['Not a string, but a dict', "Tag group name must start with 'tag_'", 'Unknown field.']}}}}
    # Always when sending Labels with Tags together. This workarround splits request  into multiple
    # Could be related to invalid tags
    CMK_22_23_HANDLE_TAG_LABEL_BUG = False

    CMK_BULK_CREATE_HOSTS = True
    CMK_BULK_CREATE_OPERATIONS = 300

    CMK_BULK_DELETE_HOSTS = True
    CMK_BULK_DELETE_OPERATIONS = 50

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
