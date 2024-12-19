"""
States for the Syncer
"""
from application import db
class State(db.Document):
    """
    Config Values
    """
    open_changes = db.IntField()
