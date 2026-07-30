"""
Host maintenance helpers.

Bulk operations over the whole host collection that are shared between the
CLI (`sys` commands) and the web UI (Data Quality dashboard), kept out of the
already large Host model module.
"""
from mongoengine.errors import NotUniqueError

from application.models.host import Host


def lowercase_all_hostnames(apply=False):
    """
    Rename hosts that have uppercase letters in their name to lowercase.

    Templates are left alone (their name is an identifier, not a hostname).
    A host is reported as a *collision* and skipped when its lowercase name is
    already taken by another host, since the hostname is unique — this includes
    archived hosts, which keep occupying their name.

    Plans only by default; pass ``apply=True`` to write the renames. Returns a
    summary dict with ``renamed`` (list of ``{'old','new'}``), ``collisions``
    (list of ``{'old','target'}``) and ``total`` (number of hosts inspected).
    """
    existing = {host.hostname for host in
                Host.objects(object_type__ne='template').only('hostname')}
    renamed = []
    collisions = []
    planned = set()
    # Deterministic order so the same host always wins a collision.
    for name in sorted(existing):
        lower = name.lower()
        if name == lower:
            continue
        if lower in existing or lower in planned:
            collisions.append({'old': name, 'target': lower})
            continue
        planned.add(lower)
        renamed.append({'old': name, 'new': lower})

    if apply:
        for pair in list(renamed):
            try:
                Host.objects(hostname=pair['old']).update(
                    set__hostname=pair['new'])
            except NotUniqueError:
                # Lost a race against a concurrent create/rename.
                renamed.remove(pair)
                collisions.append({'old': pair['old'], 'target': pair['new']})

    return {
        'renamed': renamed,
        'collisions': collisions,
        'total': len(existing),
        'applied': apply,
    }
