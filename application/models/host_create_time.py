"""
The timestamp that says when a host was created.

``create_time`` used to be written by the one import path that creates a
host, so a host added in the GUI, a clone and everything the CSV import
made had none — and "which hosts were created today?" could only be
answered for part of the database. The receiver below is wired to
``Host`` pre_save in ``application.models.host``, which puts the stamp
on every path that can ever write a host, present and future.

It lives in its own module so the rule can be tested without standing
up the whole Host document.
"""
import datetime


def stamp_create_time(_sender, document, **_kwargs):
    """
    Record when a host was created, whichever path created it — an
    import, the GUI form, a clone, the CSV import or the API. The
    timestamp is UTC like every other one the syncer stores; the web UI
    converts it to the reader's timezone.

    Only a document that was never written gets a stamp. A host already
    in the database keeps what it has, and the hosts from before this
    was written stay empty instead of claiming they were created today
    — the host search answers for those from the generation time of
    their ``_id``.
    """
    if document.pk is None and not document.create_time:
        document.create_time = datetime.datetime.utcnow()
