"""Entry point for the ``cmdbsyncer-plugin`` console script.

Handles packaging, installing, enabling/disabling of cmdbsyncer plugins.
Registered via ``[project.scripts]`` in ``pyproject.toml``; the same
command is also available as ``./cmdbsyncer-plugin`` in a source checkout.
"""
import argparse
import json
import os
import shutil
import tarfile
import tempfile

from rich import box
from rich.console import Console
from rich.table import Table

from application.helpers.plugins import read_disabled_idents, write_disabled_idents


DISABLED_PLUGINS_FILE = "disabled_plugins.json"


def _has_invalid_plugin_root(plugin_dir):
    """Return whether the archive root is unsafe as a plugin directory."""
    if not plugin_dir or plugin_dir in {".", ".."}:
        return True
    if os.path.isabs(plugin_dir):
        return True
    if os.path.sep in plugin_dir:
        return True
    if os.path.altsep and os.path.altsep in plugin_dir:
        return True
    return False


def get_disabled_plugins():
    """Return the set of disabled plugin idents from the working dir's
    ``disabled_plugins.json``."""
    return read_disabled_idents(DISABLED_PLUGINS_FILE)


def save_disabled_plugins(disabled):
    """Write the set of disabled plugin idents to the working dir's
    ``disabled_plugins.json``."""
    write_disabled_idents(DISABLED_PLUGINS_FILE, disabled)


def get_plugins():
    """Read config of every plugin that exposes a ``plugin.json``."""
    plugins = []
    plugin_dirs = ["application/plugins", "plugins"]

    for plugin_dir in plugin_dirs:
        if not os.path.exists(plugin_dir):
            continue
        for item in os.listdir(plugin_dir):
            item_path = os.path.join(plugin_dir, item)
            if not os.path.isdir(item_path):
                continue
            plugin_json_path = os.path.join(item_path, "plugin.json")
            if not os.path.exists(plugin_json_path):
                continue
            try:
                with open(plugin_json_path, "r", encoding="utf-8") as fh:
                    plugin_data = json.load(fh)
                    plugins.append({"path": plugin_json_path, "data": plugin_data})
            except (json.JSONDecodeError, IOError) as exp:
                plugins.append({"path": plugin_json_path, "error": str(exp)})
    return plugins


def get_plugin_by_name(ident, local_only=False):
    """Return the plugin with matching ``ident`` or ``None``."""
    for plugin in get_plugins():
        if "data" not in plugin:
            continue
        if plugin["data"]["ident"] != ident:
            continue
        if local_only and not plugin["path"].startswith("plugins/"):
            continue
        return plugin
    return None


def disable(ident):
    """Disable a plugin so it will not be loaded."""
    plugin = get_plugin_by_name(ident)
    if not plugin:
        print(f"Plugin '{ident}' not found")
        return
    disabled = get_disabled_plugins()
    if ident in disabled:
        print(f"Plugin '{ident}' is already disabled")
        return
    disabled.add(ident)
    save_disabled_plugins(disabled)
    print(f"Plugin '{ident}' disabled")


def enable(ident):
    """Enable a previously disabled plugin."""
    plugin = get_plugin_by_name(ident)
    if not plugin:
        print(f"Plugin '{ident}' not found")
        return
    disabled = get_disabled_plugins()
    if ident not in disabled:
        print(f"Plugin '{ident}' is already enabled")
        return
    disabled.discard(ident)
    save_disabled_plugins(disabled)
    print(f"Plugin '{ident}' enabled")


def uninstall(ident):
    """Uninstall a locally installed plugin (internal plugins are protected)."""
    plugin = get_plugin_by_name(ident, local_only=True)
    if plugin:
        plugin_path = plugin["path"].replace("plugin.json", "")
        shutil.rmtree(plugin_path)
        print(f"Plugin {ident} uninstalled successfully")
        return
    print(f"Cannot uninstall plugin {ident}: Internal plugins cannot be removed")


def install(package_path):  # pylint: disable=too-many-branches
    """Install a plugin from a ``.syncerplugin`` tarfile.

    Extracts into a temporary staging directory first so a broken or
    partial archive cannot leave the existing plugin deleted: the
    current install is only removed once the new one is fully on disk.
    """
    if not os.path.exists(package_path):
        print(f"Error: Package file {package_path} not found")
        return

    os.makedirs("plugins", exist_ok=True)
    staging_dir = None
    try:
        with tarfile.open(package_path, "r") as tar:
            members = tar.getmembers()
            if not members:
                print("Error installing plugin: archive is empty")
                return

            plugin_dir = members[0].name.split("/")[0]
            if _has_invalid_plugin_root(plugin_dir):
                print("Error installing plugin: invalid plugin archive layout")
                return

            plugin_path = os.path.join("plugins", plugin_dir)
            real_plugin_root = os.path.realpath("plugins")
            real_plugin_path = os.path.realpath(plugin_path)
            if os.path.commonpath([real_plugin_root, real_plugin_path]) != real_plugin_root:
                print("Error installing plugin: invalid plugin target path")
                return

            staging_dir = tempfile.mkdtemp(prefix=".install-", dir="plugins")
            tar.extractall(path=staging_dir, filter="data")

        staged_plugin = os.path.join(staging_dir, plugin_dir)
        if not os.path.isdir(staged_plugin):
            print("Error installing plugin: archive did not produce expected plugin directory")
            return

        backup_path = None
        if os.path.exists(plugin_path):
            backup_path = plugin_path + ".old"
            if os.path.exists(backup_path):
                shutil.rmtree(backup_path)
            os.rename(plugin_path, backup_path)
        try:
            os.rename(staged_plugin, plugin_path)
        except OSError:
            # Roll back to the previous install if the move fails.
            if backup_path and os.path.exists(backup_path) and not os.path.exists(plugin_path):
                os.rename(backup_path, plugin_path)
            raise
        if backup_path and os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        print("Plugin installed successfully")
    except (tarfile.TarError, IOError, OSError) as exp:
        print(f"Error installing plugin: {str(exp)}")
    finally:
        if staging_dir and os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)


def pack(ident):
    """Pack the given plugin into a ``.syncerplugin`` tarfile in the CWD."""
    plugin = get_plugin_by_name(ident)
    if plugin:
        plugin_path = plugin["path"].replace("plugin.json", "")
        tar_filename = f"{plugin['data']['ident']}-{plugin['data']['version']}.syncerplugin"
        with tarfile.open(tar_filename, "w") as tar:
            tar.add(plugin_path, arcname=plugin["data"]["ident"])
        print(f"Plugin packed to {tar_filename}")


def list_plugins():
    """Print all available plugins in a rich table."""
    disabled = get_disabled_plugins()
    table = Table(title="Installed Plugins", box=box.ASCII_DOUBLE_HEAD,
                  header_style="bold blue", title_style="yellow",
                  title_justify="left", width=100)
    table.add_column("Local")
    table.add_column("Enabled")
    table.add_column("Ident")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Description")

    for plugin in get_plugins():
        if "data" not in plugin:
            continue
        is_local = "Yes" if plugin["path"].startswith("plugins/") else "No"
        data = plugin["data"]
        ident = data["ident"]
        enabled = "No" if ident in disabled else "Yes"
        table.add_row(
            is_local, enabled, ident,
            data["name"], data["version"],
            data.get("description", ""),
        )
    console = Console()
    console.print(table)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="CMDB Syncer Plugin Interface")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("list", help="List available plugins")

    pack_parser = subparsers.add_parser("pack", help="Pack a plugin")
    pack_parser.add_argument("ident", help="Plugin identifier to pack")

    install_parser = subparsers.add_parser("install", help="Install a plugin")
    install_parser.add_argument("path", help="Path to Plugin")

    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a plugin")
    uninstall_parser.add_argument("ident", help="Plugin identifier to uninstall")

    disable_parser = subparsers.add_parser("disable", help="Disable a plugin")
    disable_parser.add_argument("ident", help="Plugin identifier to disable")

    enable_parser = subparsers.add_parser("enable", help="Enable a plugin")
    enable_parser.add_argument("ident", help="Plugin identifier to enable")

    args = parser.parse_args()

    if args.command == "list":
        list_plugins()
    elif args.command == "pack":
        pack(args.ident)
    elif args.command == "install":
        install(args.path)
    elif args.command == "uninstall":
        uninstall(args.ident)
    elif args.command == "disable":
        disable(args.ident)
    elif args.command == "enable":
        enable(args.ident)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
