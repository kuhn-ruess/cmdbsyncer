"""
Load single source files of the application without importing the
package, and put the stubbed modules back afterwards.
"""
import importlib.util
import os
import sys
import types

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_source(module_name, relative_path):
    """Load a source file as `module_name`, ensuring its parent exists."""
    parent = module_name.rsplit('.', 1)[0]
    if parent and parent not in sys.modules:
        sys.modules[parent] = types.ModuleType(parent)
        sys.modules[parent].__path__ = []  # mark as package
    path = os.path.join(_REPO_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def keep_modules(names):
    """The modules now registered under `names`, for `restore_modules`."""
    return {name: sys.modules.get(name) for name in names}


def restore_modules(kept):
    """Put back what `keep_modules` saw, drop what was not there."""
    for name, module in kept.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def stub_account_macro():
    """
    syncer_jinja resolves {{ACCOUNT:...}} macros through get_account; the
    test stub of that module only needs the function to exist.
    """
    get_acc = sys.modules['application.helpers.get_account']
    if not hasattr(get_acc, 'get_account_variable'):
        get_acc.get_account_variable = lambda macro: None
