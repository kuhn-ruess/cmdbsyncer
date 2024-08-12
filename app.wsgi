"""
File to use with mod_uwsgi
"""
PATH = "/var/www/cmdbsyncer"
import sys
sys.path.insert(0, PATH)
activate_this = f'{PATH}/env/bin/activate'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))
    from application import app as application


