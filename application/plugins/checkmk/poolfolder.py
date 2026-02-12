#!/usr/bin/env/python
#pylint: disable=no-member
"""
Helper to find a free Poolfolder
"""
from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.models import CheckmkFolderPool


def _get_folders(limited=False):
    if limited:
        return CheckmkFolderPool.objects(folder_name__in=limited).order_by('folder_name')
    return CheckmkFolderPool.objects().order_by('folder_name')

def get_folder(only_pools=None):
    """ Try to find a free Pool Folder """
    
    for folder in _get_folders(only_pools):
        result = CheckmkFolderPool.objects(
            folder_name=folder.folder_name,
            folder_seats_taken__lt=folder.folder_seats,
        ).update_one(inc__folder_seats_taken=1)
        
        if result:
            # Successfully incremented, reload the folder object
            folder.reload()
            return folder
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
