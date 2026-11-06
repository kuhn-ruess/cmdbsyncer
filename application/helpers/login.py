"""
Password login shared by the REST API and the MCP server
"""
from mongoengine.errors import DoesNotExist, MultipleObjectsReturned

from application.helpers.audit import audit
from application.models.user import User


def authenticate_login(login, password):
    """
    The enabled User with this name or email and this password, or None.
    """
    query = {'$or': [{'name': login}, {'email': login}]}
    try:
        user = User.objects.get(disabled__ne=True, __raw__=query)
    except DoesNotExist:
        return None
    except MultipleObjectsReturned:
        return _authenticate_collision(login, password, query)
    return user if user.check_password(password) else None


def _authenticate_collision(login, password, query):
    """
    Several users match the same login string. Historically this happens when
    the `name` field (added later, sparse) accidentally matches another
    account's `email`. We can't drop the branch: purging or unique-indexing the
    existing duplicates breaks logins for users whose `name` was empty when the
    field was introduced. So the collision is surfaced as an audit event, to
    get it cleaned up.
    """
    candidates = list(User.objects(disabled__ne=True, __raw__=query))
    # Constant-time match: check every candidate so a wrong password
    # against the first colliding user takes the same time as the
    # last, which keeps timing from leaking *which* duplicate exists.
    match = None
    for candidate in candidates:
        if candidate.check_password(password) and match is None:
            match = candidate
    audit('user.login.collision',
          outcome='success' if match else 'failure',
          actor_type='user',
          actor_id=str(match.id) if match else None,
          actor_name=login,
          metadata={
              'reason': 'multiple users matched login string',
              'candidate_count': len(candidates),
              'candidate_ids': [str(c.id) for c in candidates],
              'matched_id': str(match.id) if match else None,
          })
    return match
