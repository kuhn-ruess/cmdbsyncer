
"""
Ansible Checkmk Modul
"""
from application.plugins.checkmk.models import CheckmkSite, CheckmkSettings
from application.modules.plugin import Plugin
from application.helpers.syncer_jinja import render_jinja

class SyncSites(Plugin):
    """
    Class for the Checkmk Site Actions

    With `settings` only the sites of that Checkmk Settings entry are in
    the inventory, so a server may carry one site per settings
    (for example a production and a test site).
    """

    name = "Checkmk Sites Inventory"
    source = "ansible_jobs"

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        if settings is not None:
            self.log_details.append(('settings', settings.name))

    def _sites(self, **filters):
        """Enabled sites of enabled settings, limited to the settings when given"""
        if self.settings is not None:
            if self.settings.enabled is False:
                return []
            filters['settings_master'] = self.settings
        else:
            filters['settings_master__in'] = list(CheckmkSettings.objects(enabled__ne=False))
        return CheckmkSite.objects(enabled=True, **filters)


    def get_site_data(self, site):
        """
        Return Inventory for site
        """
        inventory = {}
        if site.settings_master.server_user:
            inventory['ansible_user'] =  site.settings_master.server_user

        # Render Jinja Templates for various settings through the sandboxed
        # helper so admin-editable settings cannot execute arbitrary code.
        filename = render_jinja(
            site.settings_master.cmk_version_filename,
            replace_newlines=False,
            CMK_VERSION=site.settings_master.cmk_version,
            CMK_EDITION=site.settings_master.cmk_edition,
        )

        # Render user, secret, and server with syncer_jinja
        cmk_user = render_jinja(site.settings_master.cmk_user or "")
        cmk_secret = render_jinja(site.settings_master.cmk_secret or "")
        # cmk_server_address is an optional override. When it's not set, the
        # API base is the server/site we are managing anyway, which is always
        # present (server_address is required), so fall back to that instead
        # of emitting an empty, unusable URL.
        cmk_main_server = render_jinja(site.settings_master.cmk_server_address or "")
        if not cmk_main_server.strip():
            cmk_main_server = f"https://{site.server_address}/{site.name}"

        inventory.update({
            'cmk_site': site.name,
            'inital_password': site.settings_master.inital_password,
            'cmk_edition': site.settings_master.cmk_edition,
            'cmk_version': site.settings_master.cmk_version,
            'cmk_version_filename': filename,
            'installation_staging_path': site.settings_master.installation_staging_path or '',
            'subscription_username': site.settings_master.subscription_username,
            'subscription_password': site.settings_master.subscription_password,
            'download_proxy': render_jinja(site.settings_master.download_proxy or ""),
            'cmk_user': cmk_user,
            'cmk_secret': cmk_secret,
            'cmk_main_server_full': cmk_main_server,
            'cmk_downtime_range': 1,
            'webserver_certificate': site.settings_master.webserver_certificate,
            'webserver_private_certificate': site.settings_master.webserver_certificate_private_key,
            'webserver_intermediate_certificate':
                site.settings_master.webserver_certificate_intermediate,
        })
        for custom_var in site.custom_ansible_variables:
            inventory[custom_var.variable_name] = custom_var.variable_value
        return inventory

    def get_full_inventory(self):
        """
        Get Full Inventory Information for Ansible
        """
        data = {
            '_meta': {
                'hostvars' : {}
            },
            'all': {
                'hosts' : []
            },
        }
        for site in self._sites():
            hostname = site.server_address
            data['_meta']['hostvars'][hostname] = self.get_site_data(site)
            data['all']['hosts'].append(hostname)
        self.name = f"Checkmk Sites Inventory: {len(data['all']['hosts'])} sites"
        return data


    def get_host_inventory(self, hostname):
        """
        Get Inventory for single host
        """
        # Without settings a server with several sites keeps the last one,
        # as in the full inventory above.
        site = None
        for site in self._sites(server_address=hostname):
            pass
        if site is None:
            self.name = f"Checkmk Sites Inventory: {hostname} not found"
            return False
        self.name = f"Checkmk Sites Inventory: {hostname}, site {site.name}"
        return self.get_site_data(site)
