#!/usr/bin/env/python
#pylint: disable=no-member
"""
Helper to find a free Poolfolder
"""
from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.models import CheckmkFolderPool


def get_folder(only_pools=None):
    """ Try to find a free Pool Folder """
    if only_pools:
        query = CheckmkFolderPool.objects(folder_name__in=only_pools).order_by('folder_name')
    else:
        query = CheckmkFolderPool.objects().order_by('folder_name')
    for folder in query:
        if folder.has_free_seat():
            folder.folder_seats_taken += 1
            folder.save()
            return folder.folder_name
    return False


def remove_seat(folder_name):
    """ Remove a seat from Folder Pool """
    try:
        folder = CheckmkFolderPool.objects.get(folder_name=folder_name)
        if folder.folder_seats_taken > 0:
            folder.folder_seats_taken -= 1
            folder.save()
    except DoesNotExist:
        pass
