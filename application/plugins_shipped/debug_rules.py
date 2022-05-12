
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
from application.helpers.debug import ColorCodes



@app.cli.command('debug_rules')
@click.argument("hostname")
def get_cmk_data(hostname):
    """Show Rule Engine Outcome for given Host"""
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")
    action_helper = GetAction(debug=True)
    label_helper = GetLabel()
    params_helper_export = GetHostParams('export')
    params_helper_import = GetHostParams('import')

    db_host = Host.objects.get(hostname=hostname)
    db_labels = db_host.get_labels()
    labels = label_helper.filter_labels(db_labels)
    params_export = params_helper_export.get_params(hostname)
    params_import = params_helper_import.get_params(hostname)
    actions = action_helper.get_action(db_host.hostname, labels)

    print()
    print(f"{ColorCodes.HEADER} ***** Final Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Labels in DB {ColorCodes.ENDC}")
    pprint(db_labels)
    print(f"{ColorCodes.UNDERLINE}Labels after Filter {ColorCodes.ENDC}")
    pprint(labels)
    print(f"{ColorCodes.UNDERLINE}Host Rule Parameters for Export {ColorCodes.ENDC}")
    pprint(params_export)
    print(f"{ColorCodes.UNDERLINE}Host Rule Parameters for Impor {ColorCodes.ENDC}t")
    pprint(params_import)
    print(f"{ColorCodes.UNDERLINE}Actions based on Action Rules {ColorCodes.ENDC}")
    pprint(actions)
