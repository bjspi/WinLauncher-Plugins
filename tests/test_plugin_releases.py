"""Plugin releases: which versions are due, and their notes, in a real repository."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "plugin_releases.py"
spec = importlib.util.spec_from_file_location("plugin_releases", SCRIPT)
plugin_releases = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin_releases  # dataclasses look the module up.
spec.loader.exec_module(plugin_releases)
GIT_TIMEOUT_SECONDS = 60


class PluginReleasesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="plugin-releases-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )

    def plugin(self, folder: str, version: str, message: str, name: str = "") -> None:
        """Write the plugin's manifest and commit it with `message`."""
        path = self.root / "plugins" / folder
        path.mkdir(parents=True, exist_ok=True)
        lines = [f'version = "{version}"'] + ([f'name = "{name}"'] if name else [])
        (path / "plugin.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (path / "plugin.py").write_text(f"# {message}\n", encoding="utf-8")  # Always a change.
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)

    def due(self) -> dict[str, object]:
        return {r.tag: r for r in plugin_releases.due_releases(self.root)}

    def test_only_versions_without_a_release_are_due(self):
        self.plugin("ai", "1.0.0", "Add ai", "AI")
        self.plugin("ai_sessions", "2.0.0", "Add sessions")
        self.plugin("_template", "1.0.0", "Add the template")
        self.git("tag", "ai-v1.0.0")
        due = self.due()
        self.assertEqual(set(due), {"ai_sessions-v2.0.0"})
        self.assertEqual(due["ai_sessions-v2.0.0"].title, "ai_sessions 2.0.0")
        self.plugin("ai", "1.1.0", "AI 1.1.0")
        self.assertEqual(self.due()["ai-v1.1.0"].previous_tag, "ai-v1.0.0")

    def test_notes_list_the_plugins_own_commits_since_its_previous_release(self):
        self.plugin("ai", "1.0.0", "Add ai", "AI")
        self.git("tag", "ai-v1.0.0")
        self.plugin("ai", "1.0.0", "Faster search\n\n- Cache results.\n- Fewer\n  reads.", "AI")
        self.plugin("other", "1.0.0", "Change another plugin")
        self.plugin("ai", "1.1.0", "AI 1.1.0: faster search", "AI")
        release = self.due()["ai-v1.1.0"]
        notes = plugin_releases.release_notes(
            release, plugin_releases.commits_of(release, self.root)
        )
        self.assertEqual(
            notes,
            "## Changes\n\n"
            "- **Faster search**\n\n"
            "  - Cache results.\n"
            "  - Fewer\n"
            "    reads.\n\n"
            "- **AI 1.1.0: faster search**\n",
        )

    def test_the_first_release_of_a_plugin_has_its_whole_history(self):
        self.plugin("ai", "1.0.0", "Add ai")
        self.plugin("ai", "1.0.1", "Fix a crash")
        release = self.due()["ai-v1.0.1"]
        subjects = [c.subject for c in plugin_releases.commits_of(release, self.root)]
        self.assertEqual(subjects, ["Add ai", "Fix a crash"])


if __name__ == "__main__":
    unittest.main()
