#!/usr/bin/env python3
"""
Get Hosts from a CMKv2 Instance
"""
from application.helpers.import_hostnames import get_import_hosts, update_import_host
from application.modules.debug import ColorCodes as CC
from .cmk2 import CMK2



def import_hosts(account, debug=False):
    """
    Inner Host Import Call
    """
    getter = DataGeter(account)
    getter.debug = debug
    getter.run()


class DataGeter(CMK2):
    """
    Get Data from CMK
    """

    def run(self):
        """Run Actual Job"""
        if self.checkmk_version.startswith('2.2'):
            url = (
                '/domain-types/host_config/collections/all'
                '?effective_attributes=true'
            )
        else:
            url = (
                '/domain-types/host_config/collections/all'
                '?effective_attributes=true'
                '&include_links=false'
            )
        filters = False
        if import_filter := self.config.get('import_filter'):
            filters = [x.strip().lower() for x in import_filter.split(',')]


        for hostdata in self.request(url, 'GET')[0]['value']:
            hostname = hostdata['id']
            print(f"\n{CC.HEADER} Process: {hostname}{CC.ENDC}")
            if import_filter and any(hostname.lower().startswith(f) for f in filters):
                print(f"{CC.OKBLUE} *{CC.ENDC} Host blacklisted by filter, ignored")
                continue

            labels = {}
            effective_attributes = hostdata['extensions']['effective_attributes']
            labels = effective_attributes
            if 'labels' in effective_attributes:
                labels.update(effective_attributes['labels'])

            for _name, host_obj in get_import_hosts(hostname, self.config, labels):
                if not update_import_host(host_obj, labels, self.config):
                    print(f"{CC.OKBLUE} *{CC.ENDC} Host owned by diffrent source, ignored")
