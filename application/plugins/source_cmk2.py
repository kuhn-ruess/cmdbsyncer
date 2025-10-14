#!/usr/bin/env python3
"""
Get Hosts from a CMKv2 Instance
"""
import click
from application.plugins.checkmk.cmk2 import cli_cmk
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.helpers.cron import register_cronjob
from application.plugins.checkmk.cmk2 import CMK2, CmkException



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

            host_obj = Host.get_host(hostname)
            labels = {}
            effective_attributes = hostdata['extensions']['effective_attributes']
            labels = effective_attributes
            if 'labels' in effective_attributes:
                labels.update(effective_attributes['labels'])

            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
            else:
                print(f"{CC.OKBLUE} *{CC.ENDC} Host owned by diffrent source, ignored")


register_cronjob('Checkmk: Import Hosts (V2)', import_hosts)

@cli_cmk.command('import_v2')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def get_cmk_data(account, debug=False):
    """Get All hosts from a CMK 2.x Installation and add them to local db"""
    try:
        import_hosts(account, debug)
    except CmkException as error_obj:
        if debug:
            raise
        print(f'CMK Connection Error: {error_obj}')
