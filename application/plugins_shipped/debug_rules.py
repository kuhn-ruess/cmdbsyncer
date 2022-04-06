
"""
Debug Rule Outcome for given Host
"""
#pylint: disable=too-many-arguments
from pprint import pprint
import click
from application import app
from application.models.host import Host
from application.helpers.get_action import GetAction
from application.helpers.get_label import GetLabel
from application.helpers.get_hostparams import GetHostParams



@app.cli.command('debug_rules')
@click.argument("hostname")
def get_cmk_data(hostname):
    """Show Rule Engine Outcome for given Host"""
    action_helper = GetAction()
    label_helper = GetLabel()
    params_helper_export = GetHostParams('export')
    params_helper_import = GetHostParams('import')

    db_host = Host.objects.get(hostname=hostname)
    db_labels = db_host.get_labels()
    labels = label_helper.filter_labels(db_labels)
    params_export = params_helper_export.get_params(hostname)
    params_import = params_helper_import.get_params(hostname)
    actions = action_helper.get_action(db_host.hostname, labels)


    print("Debug Rules for {hostname}")
    print("- Labels in DB")
    pprint(db_labels)
    print("Labels after Filter")
    pprint(labels)
    print("Host Rule Parameters for Export")
    pprint(params_export)
    print("Host Rule Parameters for Import")
    pprint(params_import)
    print("Actions based on Action Rules")
    pprint(actions)
