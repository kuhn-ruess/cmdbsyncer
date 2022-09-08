#!/usr/bin/env python3
"""
Get all Attibutes
"""
from application.models.host import Host



def get_all_attributes():
    """
    Create dict with list of all possible attributes
    """
    collection = {}
    for host in Host.objects(available=True):
        for key, value in host.get_labels().items():
            collection.setdefault(key, [])
            if value not in collection[key]:
                collection[key].append(value)
        for key, value in host.get_inventory().items():
            collection.setdefault(key, [])
            if value not in collection[key]:
                collection[key].append(value)
    return collection
