"""
File to use with mod_uwsgi
"""
PATH = "/var/www/cmdbsyncer"
import sys
sys.path.insert(0, PATH)
from application import app as application


