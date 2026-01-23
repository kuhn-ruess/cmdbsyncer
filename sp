#!/usr/bin/env python3
import argparse
import os
import json
from rich.console import Console
from rich.table import Table
from rich import box
import tarfile
import shutil
"""
CMDB Syncer Plugin Interface
"""


def get_plugins():
    """
    Read Config of all Plugins
    """
    plugins = []
    plugin_dirs = ['application/plugins', 'plugins']

    for plugin_dir in plugin_dirs:
        if os.path.exists(plugin_dir):
            for item in os.listdir(plugin_dir):
                item_path = os.path.join(plugin_dir, item)
                if os.path.isdir(item_path):
                    plugin_json_path = os.path.join(item_path, 'plugin.json')
                    if os.path.exists(plugin_json_path):
                        try:
                            with open(plugin_json_path, 'r') as f:
                                plugin_data = json.load(f)
                                plugins.append({
                                    'path': plugin_json_path,
                                    'data': plugin_data
                                })
                        except (json.JSONDecodeError, IOError) as e:
                            plugins.append({
                                'path': plugin_json_path,
                                'error': str(e)
                            })

    return plugins


def get_plugin_by_name(ident, local_only=False):
    for plugin in get_plugins():
        if 'data' in plugin:
            if plugin['data']['ident'] == ident:
                if local_only and not plugin['path'].startswith('plugins/'):
                    continue
                return plugin

def uninstall(ident):
    plugin = get_plugin_by_name(ident, local_only=True)
    if plugin:
        plugin_path = plugin['path'].replace('plugin.json', '')
        shutil.rmtree(plugin_path)
        print(f"Plugin {ident} uninstalled successfully")
        return
    print(f"Cannot uninstall plugin {ident}: Internal plugins cannot be removed")


def install(package_path):
    """
    Install Plugin from Tarfile
    """
    if not os.path.exists(package_path):
        print(f"Error: Package file {package_path} not found")
        return
    try:
        with tarfile.open(package_path, 'r') as tar:
            # Extract plugin info first to get the plugin name
            members = tar.getmembers()
            if members:
                plugin_dir = members[0].name.split('/')[0]
                plugin_path = os.path.join('plugins', plugin_dir)
                
                # Remove existing directory if it exists
                if os.path.exists(plugin_path):
                    shutil.rmtree(plugin_path)
                
            tar.extractall(path='plugins', filter='data')
        print("Plugin installed successfully")
    except (tarfile.TarError, IOError) as e:
        print(f"Error installing plugin: {str(e)}")

def pack(ident):
    """
    Pack given Plugin to Tarfile
    """
    plugin = get_plugin_by_name(ident)
    if plugin:
        plugin_path = plugin['path'].replace('plugin.json', '')
        tar_filename = f"{plugin['data']['ident']}.syncerplugin"
        with tarfile.open(tar_filename, 'w') as tar:
            tar.add(plugin_path, arcname=plugin['data']['ident'])
        print(f"Plugin packed to {tar_filename}")

def list():
    """
    Print all Available Plugins
    """
    table = Table(title="Installed Plugins", box=box.ASCII_DOUBLE_HEAD,\
                header_style="bold blue", title_style="yellow", \
                title_justify="left", width=90)
    table.add_column("Local")
    table.add_column("ident")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Description")


    for plugin in get_plugins():
        if 'data' in plugin:
            is_local = "Yes" if plugin['path'].startswith('plugins/') else "No"
            data = plugin['data']
            table.add_row(is_local, data['ident'], data['name'], data['version'], data.get('description', ""))
    console = Console()
    console.print(table)

def main():
    parser = argparse.ArgumentParser(description='CMDB Syncer Plugin Interface')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # list command
    list_parser = subparsers.add_parser('list', help='List available plugins')
    
    # pack command
    pack_parser = subparsers.add_parser('pack', help='Pack a plugin')
    pack_parser.add_argument('ident', help='Plugin identifier to pack')
    
    # install command
    install_parser = subparsers.add_parser('install', help='Install a plugin')
    install_parser.add_argument('path', help='Path to Plugin')
    
    # uninstall command
    uninstall_parser = subparsers.add_parser('uninstall', help='Uninstall a plugin')
    uninstall_parser.add_argument('ident', help='Plugin identifier to uninstall')
    
    args = parser.parse_args()
    
    if args.command == 'list':
        list()
    elif args.command == 'pack':
        pack(args.ident)
    elif args.command == 'install':
        install(args.path)
    elif args.command == 'uninstall':
        uninstall(args.ident)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()