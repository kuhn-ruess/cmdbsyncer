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


def register_inventory_provider(name: str, factory) -> None:
    """
    Register `factory` under `name`. Last writer wins — that lets
    enterprise builds override the OSS default without monkey-patching.
    """
    _inventory_providers[name] = factory


def get_inventory_provider(name: str):
    """Instantiate the provider registered under `name`, or None."""
    factory = _inventory_providers.get(name)
    if factory is None:
        return None
    return factory()


def list_inventory_providers() -> list[str]:
    """Sorted list of registered provider names."""
    return sorted(_inventory_providers.keys())


def render_ansible_inventory(provider_name: str, *, host: str | None = None):
    """
    Render `provider_name` in the Ansible JSON format used by both the
    CLI (`cmdbsyncer inventory ansible <provider>`) and the HTTP
    endpoint (`/api/v1/inventory/ansible/<provider>`).

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
