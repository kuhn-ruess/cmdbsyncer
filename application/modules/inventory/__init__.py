"""
Cross-module inventory provider registry.

A *provider* is anything that exposes the host catalog of one Syncer
module in a way the inventory format adapters can consume. The current
adapter renders the standard Ansible JSON format
(`{"_meta": {"hostvars": ...}, "all": {"hosts": ...}, ...}`); future
adapters (e.g. Checkmk DCD-style payloads) plug in next to it without
changing the providers themselves.

Modules register their providers during plugin import. The registered
value is a *factory* — a zero-arg callable that returns a freshly
configured provider instance. We keep factories instead of singletons
so each render gets fresh rule caches and database state.

Providers must implement two methods:

    get_full_inventory()  -> dict
    get_host_inventory(hostname) -> dict | False (False = host not found)

Both shapes are already produced by the existing `AnsibleInventory`
(`application/plugins/ansible/inventory.py`) and `SyncSites`
(`application/plugins/ansible/site_syncer.py`), which is why the
registration layer can stay this thin.
"""

_inventory_providers: dict = {}
_inventory_provider_resolvers: list = []


def register_inventory_provider(name: str, factory) -> None:
    """
    Register `factory` under `name`. Last writer wins — that lets
    enterprise builds override the OSS default without monkey-patching.
    """
    _inventory_providers[name] = factory


def register_inventory_provider_resolver(resolver) -> None:
    """
    Register a fallback resolver for dynamically named providers — used
    e.g. by Ansible Projects, where the set of provider names is not
    known at app startup but grows as the user creates project records
    in the UI.

    A resolver is a callable `resolver(name) -> factory | None` returning
    a zero-arg factory if it knows `name`, else None. Optionally it
    exposes `list_names() -> list[str]` so dynamic providers show up in
    `list_inventory_providers()`.
    """
    _inventory_provider_resolvers.append(resolver)


def get_inventory_provider(name: str):
    """Instantiate the provider registered under `name`, or None.

    Static registrations win; resolvers are consulted only on miss so
    callers can override a dynamic provider by registering a static one
    with the same name (e.g. for tests).
    """
    factory = _inventory_providers.get(name)
    if factory is not None:
        return factory()
    for resolver in _inventory_provider_resolvers:
        factory = resolver(name)
        if factory is not None:
            return factory()
    return None


def list_inventory_providers() -> list[str]:
    """Sorted union of statically registered names and dynamic names
    advertised by resolvers via their optional `list_names()` hook."""
    names = set(_inventory_providers.keys())
    for resolver in _inventory_provider_resolvers:
        list_names = getattr(resolver, 'list_names', None)
        if callable(list_names):
            names.update(list_names())
    return sorted(names)


def is_reserved_provider_name(name: str) -> bool:
    """Used by Project model validators to reject names that would
    collide with statically registered providers."""
    return name in _inventory_providers


def render_ansible_inventory(provider_name: str, *, host: str | None = None):
    """
    Render `provider_name` in the Ansible JSON format used by both the
    CLI (`cmdbsyncer ansible inventory <provider>`) and the HTTP
    endpoint (`/api/v1/ansible/inventory/<provider>`).

    Returns:
        dict   — full inventory (`host=None`) or single host's vars.
        None   — provider is not registered.
        False  — provider is registered but the host is unknown.
    """
    provider = get_inventory_provider(provider_name)
    if provider is None:
        return None
    if host:
        return provider.get_host_inventory(host)
    return provider.get_full_inventory()
