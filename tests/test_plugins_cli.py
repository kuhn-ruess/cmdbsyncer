"""Regression tests for plugin installation hardening."""

import importlib.util
import io
import os
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stub_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class PluginInstallTest(unittest.TestCase):
    """Exercise defensive checks in the plugin installer."""

    @classmethod
    def setUpClass(cls):
        """Load the CLI module with lightweight `rich` stubs."""
        _stub_module("rich", box=types.SimpleNamespace(ASCII_DOUBLE_HEAD=None))
        _stub_module("rich.console", Console=object)
        _stub_module("rich.table", Table=object)

        spec = importlib.util.spec_from_file_location(
            "application.plugins_cli",
            os.path.join(REPO_ROOT, "application", "plugins_cli.py"),
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["application.plugins_cli"] = module
        spec.loader.exec_module(module)
        cls.plugins_cli = module

    def test_install_rejects_parent_directory_archive_root(self):
        """Installer must reject archive roots that escape the plugins dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = os.path.join(tmpdir, "evil.syncerplugin")
            with tarfile.open(package_path, "w") as tar:
                info = tarfile.TarInfo("../outside/plugin.json")
                payload = b'{"ident":"evil","version":"1.0.0"}'
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))

            output = io.StringIO()
            with redirect_stdout(output):
                with patch.object(self.plugins_cli.shutil, "rmtree") as mocked_rmtree:
                    self.plugins_cli.install(package_path)

            self.assertIn("invalid plugin archive layout", output.getvalue())
            mocked_rmtree.assert_not_called()
