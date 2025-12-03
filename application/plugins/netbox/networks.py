"""
Netbox Networks
"""
from application import app
from application.modules.plugin import Plugin

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)

class SyncNetboxNetwork(Plugin):
    """
    Syncronise Netbox Networks
    """



    def export_networks(self):
        """
        Syncronise Networks
        """
