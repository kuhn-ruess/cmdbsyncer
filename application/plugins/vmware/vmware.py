"""
Base VMware Class
"""
import ssl
from syncerapi.v1.core import Plugin


from application import logger
try:
    from pyVim.connect import SmartConnect
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
        # self.verify is resolved by the base Plugin from the account:
        #   False/""  -> certificate validation disabled
        #   str path  -> validate against this CA cert bundle
        #   True      -> validate against the system trust store
        if self.verify in ["", False]:
            context = ssl._create_unverified_context()  # pylint: disable=protected-access
        elif isinstance(self.verify, str):
            context = ssl.create_default_context(cafile=self.verify)
        else:
            context = ssl.create_default_context()

        self.vcenter = SmartConnect(host=self.config['address'],
                                    user=self.config['username'],
                                    pwd=self.config['password'],
                                    sslContext=context)


        if not self.vcenter:
            raise Exception("Cannot connect to vcenter")  # pylint: disable=broad-exception-raised
