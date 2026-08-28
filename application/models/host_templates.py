"""
CMDB template matching

A CMDB template is a Host document with `object_type='template'`. Its
`cmdb_match` pattern ("label:value") decides which hosts carry it.
Matching a single host happens on save (`Host.get_cmdb_template`);
re-matching the whole database is a deliberate, operator-triggered step
and lives here.
"""


def parse_cmdb_match(cmdb_match):
    """
    Split a template's `cmdb_match` pattern into its label key and
    value. Whitespace around the colon is stripped.

    Returns:
        tuple|None: (key, value), or None if the pattern is unusable.
    """
    if not cmdb_match or ':' not in cmdb_match:
        return None
    key, value = cmdb_match.split(':', 1)
    key, value = key.strip(), value.strip()
    if not key:
        return None
    return key, value


def active_templates(host):
    """
    The templates a host carries that still contribute something. An
    archived (soft-deleted) template keeps its assignment so a restore
    brings it back, but it must not feed an export or be presented as
    contributing in the meantime.

    Returns:
        list: the host's non-archived templates.
    """
    return [tmpl for tmpl in (host.cmdb_templates or [])
            if not getattr(tmpl, 'deleted_at', None)]


def merged_attribute_keys():
    """
    The attribute keys configured as merged in the System Config.

    A merged attribute collects the values of every CMDB template a
    host carries — comma separated, appended to the host's own value —
    instead of the first template providing it winning and the rest
    being dropped. Everything not listed keeps that default.

    Configured centrally on purpose: which attributes are lists is a
    property of the attribute, not of a single template, so no template
    edit can change how another template behaves.

    Returns:
        set: the configured attribute keys, empty when nothing is set.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.config import Config
    config = Config.objects().first()
    return set(config.merge_attributes or []) if config else set()


def merge_attribute_values(current, addition):
    """
    Comma-join two values of a merged attribute. Both sides may
    already be comma-separated lists; the parts keep their order and
    duplicates are dropped, so a value cannot grow just because two
    templates carry the same entry.

    Returns:
        str: the merged, comma-separated value.
    """
    parts = []
    for chunk in (current, addition):
        if chunk is None:
            continue
        for part in str(chunk).split(','):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
    return ','.join(parts)


def get_template(template_name):
    """
    Look up an assignable CMDB template by name.

    Returns:
        Host|None: the template document, or None when there is no active
        template of that name.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    return Host.objects(hostname=template_name, object_type='template',
                        deleted_at__exists=False).first()


def assign_template_by_hostname(template, hostnames, dry_run=False):
    """
    Give ``template`` to every host of ``hostnames`` that exists in the
    syncer. The template is appended to the host's existing
    ``cmdb_templates``, so assignments already on the host are kept and a
    host that carries it stays untouched.

    Args:
        template (Host): The template document to assign.
        hostnames (iterable): Hostnames to give the template to.
        dry_run (bool): Report what would happen without saving.

    Returns:
        dict: the hostnames per outcome — ``assigned`` (newly given the
        template), ``already`` (carried it before) and ``missing`` (no such
        host in the syncer).
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    result = {'assigned': [], 'already': [], 'missing': []}
    for hostname in hostnames:
        db_host = Host.objects(hostname=hostname).first()
        if not db_host:
            result['missing'].append(hostname)
            continue
        existing = list(db_host.cmdb_templates or [])
        if template.id in {entry.id for entry in existing}:
            result['already'].append(hostname)
            continue
        if not dry_run:
            db_host.cmdb_templates = existing + [template]
            # Templates feed into the cached host attributes, so drop the
            # object's cache to force a recompute on the next export.
            db_host.cache = {}
            db_host.save()
        result['assigned'].append(hostname)
    return result


def sync_template_assignment(template, remove_stale=False):
    """
    Re-run one template's label match over the whole database and give
    the template to everything matching its current `cmdb_match`.

    A host can also carry the template because somebody assigned it by
    hand, and that is indistinguishable from a leftover of an older
    pattern. Dropping it is therefore never implied: only with
    `remove_stale` do hosts that do not match lose the template again.

    A template without a usable `cmdb_match` is never assigned
    automatically at all, so all of its assignments are manual — it is
    skipped entirely.

    Args:
        template (Host): The template document to re-apply.
        remove_stale (bool): Also take the template off every host that
            does not match the pattern.

    Returns:
        tuple|None: (added, removed) host counts, or None when the
        template has no usable `cmdb_match`.
    """
    parsed = parse_cmdb_match(template.cmdb_match)
    if not parsed:
        return None
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    key, value = parsed
    # Templates never carry templates, and a soft-deleted row is on its
    # way out — neither takes part in the match.
    candidates = Host.objects(object_type__ne='template',
                              deleted_at__exists=False)
    matching = set(candidates.filter(__raw__={f'labels.{key}': value})
                   .only('id').scalar('id'))
    assigned = set(candidates.filter(cmdb_templates=template.id)
                   .only('id').scalar('id'))
    to_add = list(matching - assigned)
    to_remove = list(assigned - matching) if remove_stale else []
    # Template values are merged into the cached export attributes, so a
    # changed assignment has to take the cache with it.
    if to_add:
        Host.objects(id__in=to_add).update(
            add_to_set__cmdb_templates=template.id, set__cache={})
    if to_remove:
        Host.objects(id__in=to_remove).update(
            pull__cmdb_templates=template.id, set__cache={})
    return len(to_add), len(to_remove)


def clear_consumer_cache(_sender, document, created=False, **_kwargs):
    """
    Wired to `Host` post_save: whenever a template document is written,
    drop the export attribute cache of every host carrying it, because
    the template's values are merged into that cache. Covers every way a
    template can be edited — web UI, rule import, API and CLI — instead
    of each of them having to remember.

    A freshly created template has no consumers yet, so it is skipped.
    """
    if created or getattr(document, 'object_type', None) != 'template':
        return
    if not document.pk:
        return
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    Host.objects(cmdb_templates=document.pk).update(set__cache={})
    # A changed `cmdb_match` has to be picked up by the next host save.
    Host.clear_template_cache()
