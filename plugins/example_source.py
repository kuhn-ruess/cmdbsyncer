#"""
#Example Plugin
#"""
##pylint: disable=too-many-locals
#import click
#import requests
#from application import app
#from application.helpers.cron import register_cronjob
#from application.helpers.get_account import get_account_by_name
#from application.models.host import Host
#
#@app.cli.group(name='example')
#def example_cli():
#    """example commands"""
#
#def import_hosts(account):
#    """
#    Inner Import
#    """
#    config = get_account_by_name(account)
#    user = config['username']
#    password = config['password']
#    url = f"{config['address']}/servers"
#    response = requests.get(url, auth=(user, password), timeout=30)
#
#    all_data = response.json()['data']
#
#    for host in all_data:
#        hostname = host['name']
#        labels_dict = host['atrtibutes']
#
#        host_obj = Host.get_host(hostname)
#        host_obj.update_host(labels_dict)
#        do_save = host_obj.set_account(account_dict=config)
#        if do_save:
#            host_obj.save()
#
#@example_cli.command('import_example')
#@click.argument("account")
#def cmd_import_exampel(account):
#    """
#    Import from example
#    """
#    import_hosts(account)
#
#register_cronjob('Example: Import Hosts', import_hosts)
