"""
Host maintenance helpers.

Bulk operations over the whole host collection that are shared between the
CLI (`sys` commands) and the web UI (Data Quality dashboard), kept out of the
already large Host model module.
"""
from mongoengine.errors import NotUniqueError

from application.models.field_approval import FieldApproval
from application.models.host import Host
from application.models.host_inventory_tree import HostInventoryTree


def _rename_inventory_trees(old, new):
    """
    Move the inventory trees of a renamed host. A tree the new name already
    has for that source stays, the old one is then an orphan like any other.
    """
    for tree in HostInventoryTree.objects(hostname=old).only('source'):
        try:
            HostInventoryTree.objects(id=tree.id).update(set__hostname=new)
        except NotUniqueError:
            pass


def lowercase_all_hostnames(apply=False):
    """
    Rename hosts that have uppercase letters in their name to lowercase.

    Templates are left alone (their name is an identifier, not a hostname).
    A host is reported as a *collision* and skipped when its lowercase name is
    already taken by another host, since the hostname is unique — this includes
    archived hosts, which keep occupying their name.

    Plans only by default; pass ``apply=True`` to write the renames. Returns a
    summary dict with ``renamed`` (list of ``{'old','new','archived'}``),
    ``collisions`` (list of ``{'old','target','archived','target_archived'}``),
    ``total`` (number of hosts inspected) and ``archived`` (how many of the
    affected hosts sit in the archive). Whether a host — or the name blocking
    it — is archived is what usually explains a surprising result, so every
    entry carries that flag instead of only the plain names.
    """
    archived_by_name = {
        host.hostname: host.deleted_at is not None
        for host in Host.objects(object_type__ne='template')
        .only('hostname', 'deleted_at')
    }
    existing = set(archived_by_name)
    renamed = []
    collisions = []
    planned = set()
    # Deterministic order so the same host always wins a collision.
    for name in sorted(existing):
        lower = name.lower()
        if name == lower:
            continue
        if lower in existing or lower in planned:
            collisions.append({
                'old': name,
                'target': lower,
                'archived': archived_by_name.get(name, False),
                'target_archived': archived_by_name.get(lower, False),
            })
            continue
        planned.add(lower)
        renamed.append({
            'old': name,
            'new': lower,
            'archived': archived_by_name.get(name, False),
        })

    if apply:
        for pair in list(renamed):
            try:
                # The cached rule results still carry the old HOSTNAME.
                Host.objects(hostname=pair['old']).update(
                    set__hostname=pair['new'], set__cache={})
            except NotUniqueError:
                # Lost a race against a concurrent create/rename.
                renamed.remove(pair)
                collisions.append({
                    'old': pair['old'],
                    'target': pair['new'],
                    'archived': pair['archived'],
                    'target_archived': archived_by_name.get(pair['new'], False),
                })
                continue
            # Both are keyed by hostname: left behind they count as orphans,
            # and the next maintenance removes the tree and rejects the approval.
            _rename_inventory_trees(pair['old'], pair['new'])
            FieldApproval.objects(hostname=pair['old']).update(
                set__hostname=pair['new'])

    return {
        'renamed': renamed,
        'collisions': collisions,
        'total': len(existing),
        'archived': sum(1 for entry in renamed + collisions
                        if entry['archived']),
        'applied': apply,
    }
