#!/usr/bin/env python3
"""
Inventory Helpers
"""
from application.models.host import Host
from application.helpers.get_account import account_allows
from application.helpers.import_hostnames import import_hostnames
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
        changed = host_obj.update_inventory(key, labels, config)
        # changed is None when the host was skipped by the inventory match
        # filter; only stamp seen/sync when it was actually inventorized.
        if changed is not None:
            host_obj.mark_inventorized(changed=changed)
        print(f" {CC.OKBLUE} * {CC.ENDC} {host_obj.hostname}: Updated Inventory")
        host_obj.save()
    else:
        print(f" {CC.WARNING} * {CC.ENDC} Syncer does not have this Host")




def _inventorize_name(hostname, labels, inv_key, config, collected_by_key):
    """
    Inventorize the host of one name, and note it for the collection
    of its `inventorize_collect_by_key` value
    """
    if app_config['LOWERCASE_HOSTNAMES']:
        hostname = hostname.lower()

    # The hostname is usually just one RDN of the source object, so name
    # the full DN too when the source delivers one (LDAP)
    origin = f" ({labels['dn']})" if labels.get('dn') else ""
    print(f"{CC.OKGREEN}* {CC.ENDC} Data for {hostname}{origin}")
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
            - hostname (str): The hostname as the source delivers it; the
              rewrite_hostname of the account is applied here, once
            - labels (dict or list): Dictionary of labels, or a list that is
              wrapped as {'list': labels}
        sub_key (str, optional): Additional key suffix to append to the inventory key.
            Defaults to None.
    
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
    if not account_allows(config, 'inventorize'):
        return

    inv_key = config['inventorize_key']
    if sub_key:
        inv_key += "_" + sub_key
    collected_by_key = {}
    for source_name, labels in objects:
        if isinstance(labels, list):
            labels = {'list':labels}
        # The same names the import created the hosts under, one record
        # can stand for several of them
        for hostname in import_hostnames(source_name, config, labels):
            _inventorize_name(hostname, labels, inv_key, config, collected_by_key)

    if collected_by_key:
        print(f"{CC.OKBLUE}Run 2: {CC.ENDC} Add extra collected data")

        for hostname, subs in collected_by_key.items():
            # Loop ALL hosts to delete empty collections if not found anymore
            host_obj = Host.get_host(hostname, create=False)
            # Stringify the enumeration index — the MongoDB-key validator
            # in update_inventory() runs before _fix_key() and refuses
            # raw ints, while the on-disk shape (``<key>__0``, ``__1``, …)
            # has always been string-keyed via ``_fix_key``.
            inventorize_host(host_obj, {str(i): v for i, v in enumerate(subs)},
                             f"{inv_key}_collection", False)
