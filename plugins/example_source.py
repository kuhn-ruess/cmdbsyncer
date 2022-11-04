#!/usr/bin/env python3
"""
Example to Import Data into the System
"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes


#!!!!! uncomment this in again, it's just commented to not show it as default
# in the Parameters list of ./cmdbsyncer
#@app.cli.group(name='example')
#def cli_example():
#    """Commands from example files"""
#
#@cli_example.command('example_import') # Here you set the Job Name
#@click.argument('account') # Here the Commandline Arguments
def example_import(account):
    """Import Example Set of Host Data"""

    # First we read the Source Configuration.
    # So it's possible to Mange all Credentials from the Frontend
    # You can print source_config to see the content.  Content are the Keys
    # You see in the Frontend Account Config.
    source_config = get_account_by_name(account)
    # For the Example, I hardce this config so that
    # we not need the setup
    source_config = {
        '_id' : 'exmpale',
        'name': 'Example importer'
    }

    account_id = source_config['_id']
    account_name = source_config['name']


    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account_name}{ColorCodes.ENDC}")


    # This is the Hardcoded Example Host List,
    # with the Labels already as dict.
    hosts = [
      ('srvlx001', {'state': 'prod', 'type': 'application'}),
      ('srvlx002', {'state':'prod', 'type': 'database'}),
      ('srvlx003', {'state':'prod', 'type': 'database'}),
      ('srvlx004', {'state':'dev', 'type': 'database'}),
      ('srvlx005', {'state':'dev', 'type': 'database'}),
    ]
    print(" * Connected")


    for hostname, labels in hosts:
        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
        # Iterate over you hosts, example a API Response.
        # if you get label data from your source, map it to a Dictionary



        # With this you get an reference to the object
        # in this api. You need not take care about any
        # checking if the Object already exists
        host_obj = Host.get_host(hostname)

        # If the sync complicated, you can use this function
        # to delay the resync for an object to the given time in hours
        if not host_obj.need_import_sync(12):
            continue

        # If you wan't you can compare what you get from the Source
        # with what we have in the local DB
        if host_obj.get_labels() == labels:
            continue

        # Tell the System we found this one in our source
        host_obj.set_import_seen()
        # Advanced, you not only seen the host, you did more time consuming sync
        host_obj.set_import_sync()
        #host_obj.need_import_sync() # Use that to check if you want to to that sync


        # Use host_obj.set_source_not_found() to mark that the host is gone if needed

        # For reference we set from which source account we get
        # this information. So we can prevent to sync the same object
        # from multiple sources (if needed). Will raise an exption in that case.

        host_obj.set_account(account_id, account_name)


        # Overwrite all the Labels with them from our source
        host_obj.set_labels(labels)


        # If you wan't, you cann add logs to the object:
        # host_obj.add_log("My Message")

        # Save the Changes
        host_obj.save()
        print("   * Done")

    return 0
