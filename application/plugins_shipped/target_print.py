
"""
Just print Matching Hosts
"""
import pprint
from application import app
from application.models.host import Host
from application.helpers.get_action import GetAction
from application.helpers.get_label import GetLabel

class PrintMatches():
    """
    Print Mataches
    """

    def __init__(self):
        """
        Inital
        """
        self.action_helper = GetAction()
        self.label_helper = GetLabel()

    def run(self):
        """Run Actual Job"""
        for db_host in Host.objects():
            db_labels = db_host.get_labels()
            applied_labels, extra_actions = self.label_helper.filter_labels(db_labels)
            next_actions = self.action_helper.get_action(db_host.hostname, applied_labels)
            if not next_actions or 'ignore' in next_actions:
                continue
            print(f'Next Action: {next_actions}')
            print(f"Extra Actions for {db_host.hostname}")
            print(extra_actions)
            print(f"Labels for {db_host.hostname}")
            pprint.pprint(applied_labels)


@app.cli.command('debug_print')
def get_cmk_data():
    """Print List of all Hosts and their Labels"""
    job = PrintMatches()
    job.run()
