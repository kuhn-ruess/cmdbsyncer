#!/usr/bin/env python3
"""
Inventory Helpers
"""
from application.models.host import Host
from application.helpers.syncer_jinja import render_jinja
from application.modules.debug import ColorCodes as CC
from syncerapi.v1.core import (
    app_config,
)

def _innter_inventorize(host_obj, labels, key, config):
    """
    Add Inventorize Information to host
    """
    if host_obj:
        host_obj.update_inventory(key, labels, config)
        print(f" {CC.OKBLUE} * {CC.ENDC} {host_obj.hostname}: Updated Inventory")
        host_obj.save()
    else:
        print(f" {CC.WARNING} * {CC.ENDC} Syncer does not have this Host")

def run_inventory(config, objects):
    """
    Run the inventory proccess
    Objects needs to be a list of tuples
    (hostname, labels).
    """
    inv_key = config['inventorize_key']
    collected_by_key = {}
    for hostname, labels in objects:
        if config['rewrite_hostname']:
            hostname = Host.rewrite_hostname(hostname, config['rewrite_hostname'], labels)
        if app_config['LOWERCASE_HOSTNAMES']:
            hostname = hostname.lower()


        print(f"{CC.OKGREEN}* {CC.ENDC} Data for {hostname}")
        if collect_key := config.get('inventorize_collect_by_key'):
            if value := labels.get(collect_key):
                if rewrite := config.get('inventorize_rewrite_collect_by_key'):
                    value = render_jinja(rewrite, **labels)
                value = value.strip()
                if value != hostname:
                    collected_by_key.setdefault(value, [])
                    collected_by_key[value].append(hostname)

        if config.get('inventorize_match_by_domain'):
            for host_obj in Host.objects(hostname__endswith=hostname):
                _innter_inventorize(host_obj, labels, inv_key, config)
        else:
            host_obj = Host.get_host(hostname, create=False)
            _innter_inventorize(host_obj, labels, inv_key, config)

    if collected_by_key:
        print(f"{CC.OKBLUE}Run 2: {CC.ENDC} Add extra collected data")

        for hostname, subs in collected_by_key.items():
            # Loop ALL hosts to delete empty collections if not found anymore
            host_obj = Host.get_host(hostname, create=False)
            _innter_inventorize(host_obj, dict(enumerate(subs)), f"{inv_key}_collection", False)
