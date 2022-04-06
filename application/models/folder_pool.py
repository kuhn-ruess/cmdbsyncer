"""
Folder Pool Model
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db


class FolderPool(db.Document):
    """
    Folder Pool
    """


    folder_name = db.StringField(required=True, unique=True)
    folder_seats = db.IntField(required=True)
    folder_seats_taken = db.IntField(default=0)

    enabled = db.BooleanField()


    meta = {
        'strict': False,
    }

    def has_free_seat(self):
        """
        Check if the Pool has a free Seat
        """
        if self.folder_seats_taken < self.folder_seats:
            return True
        return False
