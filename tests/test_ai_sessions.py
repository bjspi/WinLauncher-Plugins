"""Real host loading, local metadata formats, exclusions and safe terminal resume."""

from __future__ import annotations

import base64
import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from winlauncher.plugins.api import PluginContext, PluginError, PluginItem
from winlauncher.plugins.host import PluginHost
from winlauncher.plugins.registry import discover_plugins
from winlauncher.plugins.search import plugin_query

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
FOUND = discover_plugins([PLUGINS])
PLUGIN = next(plugin for plugin in FOUND.plugins if plugin.id == "ai_sessions")
entry = sys.modules[type(PLUGIN).__module__]
package_name = entry._implementation.__name__
application = importlib.import_module(package_name + ".application")
domain = importlib.import_module(package_name + ".domain")
exclusions = importlib.import_module(package_name + ".exclusions")
terminal = importlib.import_module(package_name + ".terminal")
claude = importlib.import_module(package_name + ".readers.claude")
codex = importlib.import_module(package_name + ".readers.codex")
copilot = importlib.import_module(package_name + ".readers.copilot")
records = importlib.import_module(package_name + ".readers.records")
SESSION_ID = "01a18779-4b8b-7f50-9473-de3ca09ee959"
OTHER_ID = "a8a3bd94-458b-421d-b060-becba4b573b6"


def write_records(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


class SessionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context = PluginContext(
            self.root,
            {
                **{option.key: option.default for option in PLUGIN.options},
                **{f"{p.value}_home": str(self.root / p.value) for p in domain.Provider},
            },
        )

    def claude_transcript(self, session_id: str = SESSION_ID) -> Path:
        path = self.root / "claude" / "projects" / "project" / f"{session_id}.jsonl"
        write_records(
            path,
            [
                {
                    "type": "user",
                    "cwd": str(self.root),
                    "sessionId": session_id,
                    "message": {"content": [{"type": "text", "text": "Fix launch bug"}]},
                },
                {"type": "ai-title", "aiTitle": "Automatic title", "sessionId": session_id},
                {
                    "type": "custom-title",
                    "customTitle": "My launcher session",
                    "sessionId": session_id,
                },
            ],
        )
        return path


class DiscoveryTest(SessionTestCase):
    def test_implementation_loads_in_isolation_without_changing_import_paths(self) -> None:
        paths = list(sys.path)
        found = discover_plugins([PLUGINS])
        self.assertEqual(found.problems, [])
        other = next(plugin for plugin in found.plugins if plugin.id == PLUGIN.id)
        other_entry = sys.modules[type(other).__module__]
        self.assertNotEqual(entry._implementation.__name__, other_entry._implementation.__name__)
        self.assertEqual(sys.path, paths)

    def test_routes_icons_manifest_and_host_search(self) -> None:
        self.assertEqual(FOUND.problems, [])
        self.assertEqual(FOUND.sources[PLUGIN.id].version, "1.0.0")
        self.assertEqual({route.id for route in PLUGIN.routes}, {p.value for p in domain.Provider})
        icons = {
            application.session_item(
                domain.Session(provider, SESSION_ID, "Test", str(self.root), 1, self.root)
            ).icon
            for provider in domain.Provider
        }
        self.assertEqual(len(icons), 3)
        self.assertTrue(all(Path(icon).is_file() for icon in icons))
        self.claude_transcript()
        host = PluginHost(FOUND, self.root / "host")
        config = replace(host.default_config(PLUGIN), options=dict(self.context.options))
        state = host.refresh(PLUGIN.id, config)
        self.assertFalse(state.error)
        query = plugin_query("@claude launcher", host.keywords([config]))
        self.assertIsNotNone(query)
        result = host.search(query, [config], 10)
        self.assertEqual([hit.item.key for hit in result.hits], [f"claude:{SESSION_ID}"])
        other_query = plugin_query("@codex launcher", host.keywords([config]))
        self.assertEqual(host.search(other_query, [config], 10).hits, [])


class ReadersTest(SessionTestCase):
    def test_missing_installations_and_corrupt_provider_do_not_stop_others(self) -> None:
        with patch.object(terminal.shutil, "which", return_value=None) as lookup:
            self.assertEqual(list(PLUGIN.refresh(self.context)), [])
            self.claude_transcript()
            broken = self.root / "codex" / "state_5.sqlite"
            broken.parent.mkdir()
            broken.write_bytes(b"broken database")
            items = list(PLUGIN.refresh(self.context))
        self.assertEqual([item.key for item in items], [f"claude:{SESSION_ID}"])
        lookup.assert_not_called()

    def test_claude_titles_malformed_lines_and_subagent_exclusion(self) -> None:
        path = self.claude_transcript()
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{"type":')
        nested = path.parent / "subagents" / f"{OTHER_ID}.jsonl"
        write_records(nested, [{"type": "user", "cwd": str(self.root)}])
        sidechain = path.with_name(f"{OTHER_ID}.jsonl")
        write_records(sidechain, [{"type": "user", "cwd": str(self.root), "isSidechain": True}])
        found = list(claude.claude_sessions(self.root / "claude", self.context.cancel))
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].id, found[0].title), (SESSION_ID, "My launcher session"))

    def test_claude_reads_a_recent_title_after_large_tool_output(self) -> None:
        path = self.claude_transcript()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps({"type": "assistant", "content": "x" * records.SAMPLE_BYTES * 4}) + "\n"
            )
            stream.write(
                json.dumps({"type": "custom-title", "customTitle": "Renamed recently"}) + "\n"
            )
        found = list(claude.claude_sessions(self.root / "claude", self.context.cancel))
        self.assertEqual(found[0].title, "Renamed recently")

    def test_codex_database_ignores_archived_and_internal_threads(self) -> None:
        home = self.root / "codex"
        home.mkdir()
        rollout = home / "rollout.jsonl"
        rollout.write_text("", encoding="utf-8")
        with closing(sqlite3.connect(home / "state_5.sqlite")) as database, database:
            database.execute(
                "CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, "
                "source TEXT, rollout_path TEXT, archived INTEGER)"
            )
            for source, archived, title in [
                ("cli", 0, "My Codex session"),
                ("cli", 1, "Archived"),
                ('{"subagent": {}}', 0, "Subagent"),
                ("exec", 0, "Batch job"),
            ]:
                database.execute(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (SESSION_ID, title, str(self.root), 123, source, str(rollout), archived),
                )
        found = list(codex.codex_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual([session.title for session in found], ["My Codex session"])
        self.assertEqual(found[0].updated, 123)
        with closing(sqlite3.connect(home / "state_5.sqlite")) as database, database:
            database.execute("ALTER TABLE threads ADD COLUMN name TEXT")
            database.execute("UPDATE threads SET name = 'Chosen Codex name'")
        found = list(codex.codex_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual([session.title for session in found], ["Chosen Codex name"])

    def test_codex_rollout_fallback_and_last_index_title_wins(self) -> None:
        home = self.root / "codex"
        path = home / "sessions" / "2026" / "11" / "rollout.jsonl"
        write_records(
            path,
            [
                {
                    "type": "session_meta",
                    "payload": {"id": SESSION_ID, "cwd": str(self.root), "source": "cli"},
                }
            ],
        )
        write_records(
            home / "session_index.jsonl",
            [
                {"id": SESSION_ID, "thread_name": "Old name"},
                {"id": SESSION_ID, "thread_name": "Current name"},
            ],
        )
        (home / "state_8.sqlite").write_bytes(b"not a database")
        found = list(codex.codex_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual([session.title for session in found], ["Current name"])

    def test_copilot_uses_summary_and_falls_back_to_first_prompt(self) -> None:
        home = self.root / "copilot"
        write_records(
            home / "session-state" / SESSION_ID / "events.jsonl",
            [
                {
                    "type": "session.start",
                    "data": {"sessionId": SESSION_ID, "context": {"cwd": str(self.root)}},
                },
                {"type": "user.message", "data": {"content": "First prompt"}},
            ],
        )
        found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual(found[0].title, "First prompt")
        with closing(sqlite3.connect(home / "session-store.db")) as database, database:
            database.execute("CREATE TABLE sessions (id TEXT, summary TEXT)")
            database.execute("INSERT INTO sessions VALUES (?, ?)", (SESSION_ID, "Saved summary"))
            database.execute(
                "INSERT INTO sessions VALUES (?, ?)", (OTHER_ID, "No local transcript")
            )
        found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual([session.title for session in found], ["Saved summary"])
        workspace = home / "session-state" / SESSION_ID / "workspace.yaml"
        workspace.write_text(
            "name: |-\n  My chosen name\n  Second line\nuser_named: true\n"
            + "cwd: "
            + json.dumps(str(self.root / "renamed project"))
            + "\n",
            encoding="utf-8",
        )
        found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual(found[0].title, "My chosen name\nSecond line")
        self.assertEqual(found[0].cwd, str(self.root / "renamed project"))

    def test_copilot_corrupt_yaml_falls_back_to_events(self) -> None:
        home = self.root / "copilot"
        folder = home / "session-state" / SESSION_ID
        write_records(
            folder / "events.jsonl",
            [
                {"type": "session.start", "data": {"context": {"cwd": str(self.root)}}},
                {"type": "user.message", "data": {"content": "Fallback title"}},
            ],
        )
        workspace = folder / "workspace.yaml"
        workspace.write_text("name: [\n", encoding="utf-8")
        found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual(found[0].title, "Fallback title")
        workspace.write_text("name: 'Custom name'\n", encoding="utf-8")
        with patch.dict(sys.modules, {"yaml": None}):
            found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual(found[0].title, "Fallback title")

    def test_cancelled_refresh_returns_without_reading_sessions(self) -> None:
        self.context.cancel.set()
        self.assertEqual(list(PLUGIN.refresh(self.context)), [])


class ActivityFilterTest(SessionTestCase):
    def test_default_fourteen_days_configurable_window_and_count_limit(self) -> None:
        now = records.timestamp("2026-11-04T12:00:00Z")
        for session_id, activity in [
            (SESSION_ID, "2026-10-25T12:00:00Z"),
            (OTHER_ID, "2026-10-10T12:00:00Z"),
        ]:
            path = self.claude_transcript(session_id)
            write_records(
                path,
                [
                    {
                        "type": "user",
                        "cwd": str(self.root),
                        "timestamp": activity,
                        "message": {"content": "Old conversation"},
                    },
                    {
                        "type": "custom-title",
                        "customTitle": "Renamed today",
                        "timestamp": "2026-11-04T12:00:00Z",
                    },
                ],
            )
        with patch.object(application.time, "time", return_value=now):
            self.assertEqual(
                [item.key for item in PLUGIN.refresh(self.context)], [f"claude:{SESSION_ID}"]
            )
            recent = PluginContext(self.root, {**self.context.options, "max_age_days": 7})
            self.assertEqual(list(PLUGIN.refresh(recent)), [])
            all_ages = PluginContext(self.root, {**self.context.options, "max_age_days": 0})
            self.assertEqual(len(list(PLUGIN.refresh(all_ages))), 2)
            limited = PluginContext(self.root, {**all_ages.options, "limit": 1})
            self.assertEqual(
                [item.key for item in PLUGIN.refresh(limited)], [f"claude:{SESSION_ID}"]
            )

    def test_copilot_uses_last_message_instead_of_later_shutdown(self) -> None:
        home = self.root / "copilot"
        write_records(
            home / "session-state" / SESSION_ID / "events.jsonl",
            [
                {"type": "session.start", "data": {"context": {"cwd": str(self.root)}}},
                {
                    "type": "user.message",
                    "timestamp": "2026-10-01T12:00:00Z",
                    "data": {"content": "Question"},
                },
                {
                    "type": "assistant.message",
                    "timestamp": "2026-10-02T12:00:00Z",
                    "data": {"content": "Answer"},
                },
                {"type": "session.shutdown", "timestamp": "2026-11-04T12:00:00Z", "data": {}},
            ],
        )
        found = list(copilot.copilot_sessions(home, self.context.cancel, self.context.log))
        self.assertEqual(found[0].updated, records.timestamp("2026-10-02T12:00:00Z"))


class ExclusionTest(SessionTestCase):
    def test_exclusion_survives_reload_and_can_be_restored(self) -> None:
        transcript = self.claude_transcript()
        original = transcript.read_bytes()
        answers = iter([SESSION_ID, "1"])
        context = PluginContext(
            self.root, self.context.options, ask=lambda *args, **kwargs: next(answers)
        )
        self.assertIn("excluded", application.exclude_session(context))
        self.assertEqual(list(PLUGIN.refresh(self.context)), [])
        self.assertEqual(transcript.read_bytes(), original)
        self.assertIn(f"claude:{SESSION_ID}", exclusions.read_exclusions(self.root))
        answers = iter(["launcher", "1"])
        self.assertIn("restored", application.restore_session(context))
        self.assertEqual(len(list(PLUGIN.refresh(self.context))), 1)
        self.assertEqual(transcript.read_bytes(), original)

    def test_cancelling_selection_does_not_exclude_anything(self) -> None:
        self.claude_transcript()
        answers = iter([SESSION_ID, None])
        context = PluginContext(
            self.root, self.context.options, ask=lambda *args, **kwargs: next(answers)
        )
        self.assertIsNone(application.exclude_session(context))
        self.assertEqual(exclusions.read_exclusions(self.root), {})

    def test_damaged_exclusions_fail_instead_of_resurfacing_sessions(self) -> None:
        (self.root / exclusions.EXCLUSIONS_FILE).write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(PluginError, "excluded sessions"):
            PLUGIN.refresh(self.context)

    def test_hidden_cached_item_cannot_be_opened(self) -> None:
        key = f"claude:{SESSION_ID}"
        exclusions.write_exclusions(self.root, {key: "Hidden"})
        with patch.object(application, "resume_session") as resume:
            with self.assertRaisesRegex(PluginError, "excluded"):
                PLUGIN.open(PluginItem(key, "Hidden"), self.context)
        resume.assert_not_called()

    def test_exclusions_apply_before_the_visible_limit(self) -> None:
        self.claude_transcript()
        self.claude_transcript(OTHER_ID)
        exclusions.write_exclusions(self.root, {f"claude:{SESSION_ID}": "Hidden"})
        context = PluginContext(self.root, {**self.context.options, "limit": 1})
        self.assertEqual([item.key for item in PLUGIN.refresh(context)], [f"claude:{OTHER_ID}"])


class ResumeTest(SessionTestCase):
    def test_each_cli_gets_its_resume_command_in_a_visible_terminal(self) -> None:
        project = self.root / "project's $x; space"
        project.mkdir()
        for provider in domain.Provider:
            for use_terminal in (True, False):
                with self.subTest(provider=provider, terminal=use_terminal):
                    item = application.session_item(
                        domain.Session(provider, SESSION_ID, "Name", str(project), 0, self.root)
                    )

                    def which(name: str, use_terminal: bool = use_terminal) -> str | None:
                        if name == "wt.exe" and not use_terminal:
                            return None
                        return f"C:/Program Files/{name}"

                    with (
                        patch.object(terminal.shutil, "which", side_effect=which),
                        patch.object(terminal.subprocess, "Popen") as launch,
                    ):
                        terminal.resume_session(application.session_from_item(item))
                    command = launch.call_args.args[0]
                    script = base64.b64decode(command[-1]).decode("utf-16-le")
                    expected = "resume" if provider == domain.Provider.CODEX else "--resume"
                    self.assertIn(f"{expected} '{SESSION_ID}'", script)
                    self.assertIn("project''s $x; space", script)
                    self.assertIn(f"$env:{provider.home_variable}", script)
                    self.assertEqual(launch.call_args.kwargs["cwd"], str(project))
                    self.assertEqual("new-tab" in command, use_terminal)
                    self.assertIn("-NoExit", command)
                    self.assertNotIn("shell", launch.call_args.kwargs)

    def test_missing_cli_or_project_gives_an_actionable_error(self) -> None:
        item = application.session_item(
            domain.Session(domain.Provider.CODEX, SESSION_ID, "Name", str(self.root), 0, self.root)
        )
        with patch.object(terminal.shutil, "which", return_value=None):
            with self.assertRaisesRegex(domain.SessionError, "PATH"):
                terminal.resume_session(application.session_from_item(item))
        missing = application.session_item(
            domain.Session(
                domain.Provider.CODEX, SESSION_ID, "Name", str(self.root / "gone"), 0, self.root
            )
        )
        with self.assertRaisesRegex(domain.SessionError, "no longer exists"):
            terminal.resume_session(application.session_from_item(missing))

    def test_invalid_session_id_cannot_become_a_command_argument(self) -> None:
        item = PluginItem(
            "bad",
            "Bad",
            data={
                "provider": "codex",
                "id": "--last; echo test",
                "cwd": str(self.root),
                "home": str(self.root),
            },
        )
        with patch.object(terminal.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(domain.SessionError, "invalid session ID"):
                terminal.resume_session(application.session_from_item(item))
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
