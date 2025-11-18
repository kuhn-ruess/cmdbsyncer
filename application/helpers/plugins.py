import os
import json

def discover_plugins():
    """
    Discover account types from plugin.json files in plugin directories
    """
    plugins = {}
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    plugin_dirs = [
        os.path.join(base_dir, 'plugins'),
        os.path.join(base_dir, 'application', 'plugins')
    ]
    for plugin_dir in plugin_dirs:
        if not os.path.exists(plugin_dir):
            continue
        # Walk through all subdirectories
        for root, dirs, files in os.walk(plugin_dir):
            if 'plugin.json' in files:
                plugin_json_path = os.path.join(root, 'plugin.json')
                try:
                    with open(plugin_json_path, 'r', encoding='utf-8') as f:
                        plugin_data = json.load(f)
                        
                    if 'ident' in plugin_data and 'name' in plugin_data:
                        ident = plugin_data['ident']
                        plugins[ident] = plugin_data
                        
                except (json.JSONDecodeError, FileNotFoundError, KeyError):
                    # Skip invalid or incomplete plugin.json files
                    continue
    return plugins