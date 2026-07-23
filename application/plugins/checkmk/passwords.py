"""
Checkmk DCD Manager
"""
# pylint: disable=duplicate-code

import hashlib
import json

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.plugins.checkmk.models import CheckmkPassword
from application.plugins.checkmk.cmk2 import CMK2


class CheckmkPasswordSync(CMK2):
    """
    Sync Checkmk Passwords
    """
    console = None

    name = "Sync Passwords to Checkmk"
    source = "cmk_password_sync"

    def __init__(self, account=False):
        super().__init__(account)
        # Per-instance run state. A class-level list would accumulate
        # password IDs across repeated runs and let stale entries flip
        # create/update decisions.
        self.current_password_ids = []

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

    @staticmethod
    def payload_hash(payload):
        """
        Stable hash of the payload we send to Checkmk. Used to skip
        re-exporting passwords that haven't changed since the last run.
        Checkmk never returns the stored secret, so we can't diff against
        Checkmk itself; hashing the desired payload also catches secret
        rotations locally.
        """
        raw = json.dumps(payload, sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def create_password(self, password, payload=None):
        """
        Create not existing Password in checkmk
        """
        self.console(f" * Create Password {password['name']}")
        url = "/domain-types/password/collections/all"
        if payload is None:
            payload = self.build_payload(password)
        self.request(url, method="POST", data=payload)

    def update_password(self, password, payload=None):
        """
        Update Password in Checkmk
        """
        self.console(f" * Update Password {password['name']}")
        if payload is None:
            payload = self.build_payload(password)
        else:
            payload = dict(payload)
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
                payload = self.build_payload(password)
                payload_hash = self.payload_hash(payload)
                if password_id not in self.current_password_ids:
                    self.create_password(password, payload)
                elif password.last_export_hash != payload_hash:
                    self.update_password(password, payload)
                else:
                    # Nothing changed since the last export, skip the PUT.
                    progress.advance(task2)
                    continue
                password.last_export_hash = payload_hash
                password.save()
                progress.advance(task2)
