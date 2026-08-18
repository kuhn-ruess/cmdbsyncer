"""
Cleanup of the documents that hang off a Host but cannot be reached by a
MongoEngine delete rule.

Three stores need this. ``HostInventoryTree`` and ``FieldApproval`` are
keyed by the hostname / id as a plain string, so no rule can be attached
at all. ``HostRelation.target_host`` is a reference inside an embedded
document, where MongoEngine has no document-level hook to hang a rule
on — a deleted host would otherwise leave a dangling reference in every
host that pointed at it, and dereferencing that raises ``DoesNotExist``
rather than returning ``None``.

``HostLabelEvent`` is deliberately absent: it holds a real
``ReferenceField`` with ``reverse_delete_rule=CASCADE``, which
MongoEngine applies on both the single-document and the bulk path.

The module also owns ``relation_target()``, the read side of the same
problem: databases written by earlier versions still carry dangling
references, and every caller that reads one has to survive them until
``cmdbsyncer sys maintenance`` has repaired the data.
"""
import datetime

from mongoengine import QuerySet
from mongoengine.errors import DoesNotExist


def relation_target(relation):
    """
    The Host a relation points at, or ``None`` if it points at a deleted
    one.

    Reading ``relation.target_host`` directly is not safe: MongoEngine
    raises ``DoesNotExist`` on a dangling reference rather than returning
    ``None``, so the obvious ``if not rel.target_host`` guard never runs —
    the line that would set up the check has already raised. Deletions go
    through ``HostQuerySet`` now, but references left behind by earlier
    versions are still out there.
    """
    try:
        return relation.target_host
    except DoesNotExist:
        return None


def _purge_side_documents(host_ids, hostnames):
    """Drop / neutralise everything keyed to these hosts."""
    # Imported here: these modules import Host themselves, so a
    # module-level import would be circular.
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    from application.models.host_inventory_tree import HostInventoryTree
    from application.models.field_approval import FieldApproval

    if hostnames:
        HostInventoryTree.objects(hostname__in=hostnames).delete()
        # Decided approvals already expire through their TTL. Pending ones
        # deliberately never do, so a queue entry for a host that no longer
        # exists would sit there forever and keep counting towards the
        # "pending" badge. Reject them instead of deleting, so the decision
        # trail survives and the existing TTL clears them on schedule.
        FieldApproval.objects(hostname__in=hostnames, status='pending').update(
            set__status='rejected',
            set__decided_at=datetime.datetime.utcnow(),
            set__decision_reason='Host was deleted',
        )

    if host_ids:
        Host.objects(__raw__={'relations.target_host': {'$in': host_ids}}).update(
            __raw__={'$pull': {'relations': {
                'target_host': {'$in': host_ids}}}},
        )


class HostQuerySet(QuerySet):
    """
    Host queryset that cleans up a host's side documents on delete.

    Deliberately hooked in here rather than on the `post_delete` signal:
    MongoEngine turns every `Host.objects(...).delete()` into a
    per-document Python loop as soon as the class has a delete-signal
    receiver, which would make a bulk delete of a large fleet one round
    trip per host. `Document.delete()` routes through
    `self._qs.filter(...).delete()`, so overriding the queryset covers
    the single-host path too — one place, both paths, no loop.
    """

    def delete(self, *args, **kwargs):
        # Collect the keys before the documents are gone; afterwards the
        # query no longer matches anything.
        identified = [(host.pk, host.hostname)
                      for host in self.clone().only('hostname')]
        result = super().delete(*args, **kwargs)
        if identified:
            _purge_side_documents([pk for pk, _ in identified],
                                  [name for _, name in identified])
        return result
