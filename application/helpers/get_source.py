"""
Helper to get Source
"""
from application.models.source import Source
from mongoengine.errors import DoesNotExist


def get_source_by_name(name):
    """
    Get Source by Name or Return False
    """

    try:
        return dict(Source.objects.get(name=name, enabled=True).to_mongo())
    except DoesNotExist:
        return False
