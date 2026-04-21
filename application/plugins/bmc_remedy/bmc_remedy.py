"""
BMC Remedy Plugin
"""
from syncerapi.v1 import (
    cc,
    Host,
)

from application.modules.plugin import Plugin


class RemedyAuthError(Exception):
    """Raised on BMC Remedy authentication failures."""


class RemedySyncer(Plugin):
    """
    BMC Remedy
    """

    #   .-- get_auth_token
    def get_auth_token(self):
        """
        Return Auth Token
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Get Auth Token")
        url = f"{self.config['address']}/api/jwt/login"
        auth_data = {
            'username': self.config['username'],
            'password': self.config['password'],
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = self.inner_request(
            method="POST",
            url=url,
            data=auth_data,
            headers=headers,
        )

        if response.status_code == 200:
            return response.text
        raise RemedyAuthError(
            f"Authentication failed with status {response.status_code}"
        )

    #.
    #    .-- Get Hosts
    def get_hosts(self):
        """
        Import hosts from BMC Remedy into the Syncer. Each returned entry
        is mapped to a Host via the configured ``hostname_field`` and the
        remaining attributes are stored as labels, consistent with the
        other importers.
        """
        auth_token = self.get_auth_token()
        url = (
            f"{self.config['address']}/api/cmdb/v1.0/classqueries/"
            f"{self.config['namespace']}/{self.config['class_name']}"
        )
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'AR-JWT {auth_token}',
        }

        response = self.inner_request(method="GET", url=url, headers=headers)
        payload = response.json()

        # BMC Remedy returns results under 'entries' (each with a
        # 'values' dict); fall back to a flat list for pre-v9 payloads.
        entries = payload.get('entries') or payload.get('values') or []
        hostname_field = self.config['hostname_field']

        for entry in entries:
            labels = entry.get('values', entry) if isinstance(entry, dict) else entry
            if not isinstance(labels, dict):
                continue
            hostname = labels.get(hostname_field)
            if not hostname:
                continue

            host_obj = Host.get_host(hostname)
            attrs = {k: v for k, v in labels.items() if k != hostname_field}
            host_obj.update_host(attrs)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
                print(f" {cc.OKGREEN}* {cc.ENDC} Update {hostname}")
            else:
                print(f" {cc.WARNING} * {cc.ENDC} {hostname}: managed by a different source")


def get_hosts(account, debug=False):
    """
    Get Remedy Hosts
    """
    job = RemedySyncer(account)
    job.debug = debug
    job.name = "BMC Remedy: Import Hosts"
    job.source = "bmc_remedy_import"
    job.get_hosts()
