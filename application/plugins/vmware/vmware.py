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
        connect_args = {
            'host': self.config['address'],
            'user': self.config['username'],
            'pwd': self.config['password'],
        }
        # self.verify is resolved by the base Plugin from the account:
        #   False/""  -> certificate validation disabled
        #   str path  -> validate against this CA cert bundle
        #   True      -> validate against the system trust store
        # pyVmomi only skips validation when its own disableSslCertValidation
        # flag is set, so use that rather than relying on an unverified
        # sslContext alone.
        if self.verify in ["", False]:
            connect_args['disableSslCertValidation'] = True
        elif isinstance(self.verify, str):
            connect_args['sslContext'] = ssl.create_default_context(cafile=self.verify)

        if self.debug:
            print(f"VMware connect: address={self.config['address']} "
                  f"verify={self.verify!r} "
                  f"disableSslCertValidation="
                  f"{connect_args.get('disableSslCertValidation', False)}")

        self.vcenter = SmartConnect(**connect_args)

        if not self.vcenter:
            raise Exception("Cannot connect to vcenter")  # pylint: disable=broad-exception-raised
