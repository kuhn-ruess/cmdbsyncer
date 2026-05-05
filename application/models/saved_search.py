"""
Saved Search / Filter Preset

A named snapshot of a Flask-Admin list-view URL (path + query string)
that an operator can re-open with one click. Owned by the user that
created it; flipping `shared` makes it visible to every other operator
without giving away ownership.
"""
import datetime
from application import db


class SavedSearch(db.Document):
    """
    Persistent filter preset.

    `path`         the relative admin URL the preset opens (e.g. '/admin/host/')
    `query_string` the search/filter URL fragment captured when the
                   user clicked Save (e.g. 'flt0_lifecycle=active&search=db')
    `owner_email`  the email of the user that created it; used to
                   decide whether the current user can delete it.
    `shared`       broadcast the preset to every operator; the owner
                   stays the sole user that can delete it.
    """
    name = db.StringField(required=True, max_length=120)
    path = db.StringField(required=True, max_length=255)
    query_string = db.StringField(required=True)
    owner_email = db.StringField(max_length=255, required=True)
    shared = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.datetime.utcnow, required=True)

    meta = {
        'collection': 'saved_search',
        'indexes': [
            {'fields': ['owner_email', 'path']},
            {'fields': ['shared', 'path']},
        ],
        'ordering': ['-created_at'],
    }

    def __str__(self):
        scope = 'shared' if self.shared else 'private'
        return f"SavedSearch '{self.name}' ({scope}) by {self.owner_email}"
