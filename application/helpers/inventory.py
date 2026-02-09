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

def inventorize_host(host_obj, labels, key, config):
    """
    Add Inventorize Information to host
    """
    if host_obj:
        host_obj.update_inventory(key, labels, config)
        print(f" {CC.OKBLUE} * {CC.ENDC} {host_obj.hostname}: Updated Inventory")
        host_obj.save()
    else:
        print(f" {CC.WARNING} * {CC.ENDC} Syncer does not have this Host")




def run_inventory(config, objects, sub_key=None):
    """
    Execute the inventory process for a collection of hosts and their associated labels.
    
    This function processes host inventory data by iterating through host objects,
    applying hostname transformations, and storing inventory information. It supports
    collecting hosts by a specified key and can match hosts by domain patterns.
    
    Args:
        config (dict): Configuration dictionary containing inventory settings including:
            - inventorize_key: Base key for inventory storage
            - rewrite_hostname: Optional hostname rewriting configuration
            - inventorize_collect_by_key: Key to collect hosts by
            - inventorize_rewrite_collect_by_key: Jinja template for rewriting collect key values
            - inventorize_match_by_domain: Boolean flag for domain-based host matching
        objects (list): List of tuples in the format (hostname, labels) where:
            - hostname (str): The hostname of the host
            - labels (dict or list): Dictionary of labels or list that will be converted to {'list': labels}
        sub_key (str, optional): Additional key suffix to append to the inventory key. Defaults to None.
    
    Returns:
        None
    
    Side Effects:
        - Prints progress information to stdout
        - Calls inventorize_host() to store inventory data
        - May create or update Host objects in the database
        - Processes collected hosts in a second pass for additional data aggregation
    
    Note:
        The function performs a two-pass process:
        1. First pass: Process individual hosts and collect grouped hosts
        2. Second pass: Process collected host groups as enumerated collections
    """
    inv_key = config['inventorize_key']
    if sub_key:
        inv_key += "_" + sub_key
    collected_by_key = {}
    for hostname, labels in objects:
        if isinstance(labels, list):
            labels = {'list':labels}
        if config.get('rewrite_hostname'):
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
                inventorize_host(host_obj, labels, inv_key, config)
        else:
            host_obj = Host.get_host(hostname, create=False)
            inventorize_host(host_obj, labels, inv_key, config)

    if collected_by_key:
        print(f"{CC.OKBLUE}Run 2: {CC.ENDC} Add extra collected data")

        for hostname, subs in collected_by_key.items():
            # Loop ALL hosts to delete empty collections if not found anymore
            host_obj = Host.get_host(hostname, create=False)
            inventorize_host(host_obj, dict(enumerate(subs)), f"{inv_key}_collection", False)
