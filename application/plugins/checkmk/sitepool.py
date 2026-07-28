#!/usr/bin/env/python
"""
Helper to pick the least-loaded site from a Site Pool
"""
from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.models import CheckmkSitePool


def get_site(pool_name):
    """
    Return the least-loaded site id of the given pool and claim a seat on it.

    Least-loaded: the member site with the fewest ``hosts_taken`` wins.
    The seat is claimed with an atomic, guarded increment (matching the
    member's current counter) so parallel export workers cannot hand out the
    same seat twice; on a lost race we reload and retry. Returns ``False`` if
    the pool is missing, disabled or has no member sites.
    """
    for _attempt in range(50):
        try:
            pool = CheckmkSitePool.objects.get(name=pool_name, enabled=True)
        except DoesNotExist:
            return False

        if not pool.member_sites:
            return False

        member = min(pool.member_sites, key=lambda m: m.hosts_taken)

        # Guarded increment: only succeeds while the member's counter is still
        # what we based our choice on. ``S`` is the positional operator for the
        # array element matched by member_sites__site_id.
        result = CheckmkSitePool.objects(
            name=pool_name,
            member_sites__site_id=member.site_id,
            member_sites__hosts_taken=member.hosts_taken,
        ).update_one(inc__member_sites__S__hosts_taken=1)

        if result:
            return member.site_id
        # Lost the race, someone changed the counter, try again.
    return False


def release_site(pool_name, site_id):
    """ Free a seat on a specific site of a specific pool """
    CheckmkSitePool.objects(
        name=pool_name,
        member_sites__site_id=site_id,
        member_sites__hosts_taken__gt=0,
    ).update_one(dec__member_sites__S__hosts_taken=1)


def release_site_for_site_id(site_id):
    """
    Free a seat for a site id without knowing its pool.

    The host only stores its site id, not the pool it came from. We free the
    seat on the first enabled pool that lists this site. Counter drift is
    corrected by the ``sync_sitepools`` reconciliation job regardless.
    """
    pool = CheckmkSitePool.objects(
        member_sites__site_id=site_id,
        member_sites__hosts_taken__gt=0,
    ).first()
    if pool:
        release_site(pool.name, site_id)
