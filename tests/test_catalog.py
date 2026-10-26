"""This repository is a plugin catalog: WinLauncher must offer every plugin in it."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from winlauncher.plugins.catalog import PluginCatalogs

ROOT = Path(__file__).resolve().parent.parent
CATALOG_URL = "https://github.com/bjspi/WinLauncher-Plugins.git"


class CatalogTest(unittest.TestCase):
    def test_every_plugin_is_offered_with_a_complete_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            library = PluginCatalogs(Path(directory) / "clones", Path(directory) / "plugins")
            # Read the working tree as WinLauncher reads its clone, uncommitted edits included.
            shutil.copytree(
                ROOT,
                library.mirror(CATALOG_URL),
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".ruff_cache"),
            )
            catalog = library.read(CATALOG_URL)
        self.assertEqual((catalog.error, catalog.problems), ("", ()))
        self.assertEqual(catalog.title, "WinLauncher Plugins")
        offered = {plugin.folder: plugin for plugin in catalog.plugins}
        folders = {
            folder.name
            for folder in (ROOT / "plugins").iterdir()
            if folder.is_dir() and not folder.name.startswith("_")
        }
        self.assertEqual(set(offered), folders)
        for plugin in offered.values():
            with self.subTest(plugin=plugin.folder):
                manifest = plugin.manifest
                self.assertTrue(manifest.version and manifest.name and manifest.description)


if __name__ == "__main__":
    unittest.main()
