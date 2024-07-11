"""
Checkmk DCD Manager
"""

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.checkmk.config_sync import SyncConfiguration
from application.modules.checkmk.models import CheckmkPassword


class CheckmkPasswordSync(SyncConfiguration):
    """
    Sync Checkmk Passwords
    """
    console = None
    current_password_ids = []

    def get_current_passwords(self):
        """
        Check if Rule is existing
        """
        url = "/domain-types/password/collections/all"
        response = self.request(url, method="GET")[0]
        for entry in response['value']:
            self.current_password_ids.append(entry['id'])


    def build_payload(self, password):
        """
        Build Checkmk APIs Payload
        """
        payload = {
          "ident": f"cmdbsyncer_{password['id']}",
          "title": password['title'],
          "comment": password['comment'],
          "password": password.get_password(),
          "owner": password['owner'],
          "shared": password.shared,
        }
        if password['documentation_url']:
            payload['documentation_url'] = password['documentation_url']
        return payload

    def create_password(self, password):
        """
        Create not existing Password in checkmk
        """
        self.console(f" * Create Password {password['name']}")
        url = "/domain-types/password/collections/all"
        payload = self.build_payload(password)
        self.request(url, method="POST", data=payload)

    def update_password(self, password):
        """
        (Always) Update Password in Checkmk
        """
        self.console(f" * Update Password {password['name']}")
        payload = self.build_payload(password)
        url = f"/objects/password/{payload['ident']}"
        del payload['ident']
        self.request(url, method="PUT", data=payload)

    def export_passwords(self):
        """
        Export Passwords
        """
        # Collect Rules

        total = CheckmkPassword.objects(enabled=True).count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:

            self.console = progress.console.print

            task1 = progress.add_task("Get Current Passwords", total=None)
            self.get_current_passwords()
            progress.advance(task1)
            task2 = progress.add_task("Export Passwords", total=total)

            for password in CheckmkPassword.objects(enabled=True):
                password_id = f"cmdbsyncer_{password['id']}"
                if password_id not in self.current_password_ids:
                    self.create_password(password)
                else:
                    self.update_password(password)
                progress.advance(task2)
