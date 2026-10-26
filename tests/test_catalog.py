"""This repository is a plugin source: WinLauncher must offer every plugin in it."""

from __future__ import annotations

import unittest
from pathlib import Path

from winlauncher.plugins.folders import read_source

ROOT = Path(__file__).resolve().parent.parent


class CatalogTest(unittest.TestCase):
    def test_every_plugin_is_offered_with_a_complete_manifest(self):
        contents = read_source(ROOT)  # The working tree, as WinLauncher reads its clone.
        self.assertEqual((contents.name, contents.problems), ("WinLauncher Plugins", ()))
        offered = {plugin.folder.name: plugin for plugin in contents.plugins}
        folders = {
            folder.name
            for folder in (ROOT / "plugins").iterdir()
            if folder.is_dir() and not folder.name.startswith("_")
        }
        self.assertEqual(set(offered), folders)
        for plugin in offered.values():
            with self.subTest(plugin=plugin.folder.name):
                manifest = plugin.manifest
                self.assertTrue(manifest.version and manifest.name and manifest.description)
                self.assertIsNotNone(plugin.icon, "plugin.toml names no icon file it has")


if __name__ == "__main__":
    unittest.main()
