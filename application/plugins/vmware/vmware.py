"""
Base VMware Class
"""
import ssl
from syncerapi.v1.core import Plugin


from application import logger, app
try:
    from pyVmomi import vim
    from pyVim.connect import SmartConnect, Disconnect
except ImportError:
    logger.info("Info: VMware Plugin was not able to load required modules")

class VMWareVcenterPlugin(Plugin):
    """
    Base VMware Vcenter Plugin
    """
    vcenter = None
    content = None

    def connect(self):
        """
        Connect to VMware
        """
        if app.config.get('DISABLE_SSL_ERRORS'):
            # pylint: disable=protected-access
            context = ssl._create_unverified_context()
        else:
            context = ssl.create_default_context()

        self.vcenter = SmartConnect(host=self.config['address'],
                                    user=self.config['username'],
                                    pwd=self.config['password'],
                                    sslContext=context)


        if not self.vcenter:
            raise Exception("Cannot connect to vcenter")
