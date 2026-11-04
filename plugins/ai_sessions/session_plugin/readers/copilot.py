"""GitHub Copilot CLI local summaries and event metadata."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import SAMPLE_BYTES, message_text, read_database, sampled_records, text, timestamp


@dataclass(frozen=True, slots=True)
class CopilotWorkspace:
    """The latest CLI metadata, including a name explicitly chosen by the user."""

    cwd: str = ""
    name: str = ""
    user_named: bool = False


def copilot_sessions(home: Path, cancel: threading.Event, log: logging.Logger) -> Iterator[Session]:
    """Only local CLI sessions with an events file can be resumed this way."""
    summaries: dict[str, str] = {}
    database = home / "session-store.db"
    if database.is_file():
        try:
            rows = read_database(database, "SELECT id, summary FROM sessions")
            summaries = {text(row["id"]): text(row["summary"]) for row in rows}
        except sqlite3.Error as exc:
            log.info("Copilot metadata unavailable; reading events: %s", exc)
    for path in (home / "session-state").glob("*/events.jsonl"):
        if cancel.is_set():
            return
        session_id = path.parent.name
        if not valid_id(session_id):
            continue
        workspace = read_workspace(path.with_name("workspace.yaml"), log)
        cwd = workspace.cwd
        title = (
            workspace.name if workspace.user_named else summaries.get(session_id) or workspace.name
        )
        last_message = 0.0
        for record in sampled_records(path):
            data = record.get("data")
            if not isinstance(data, dict):
                continue
            if record.get("type") in ("user.message", "assistant.message"):
                last_message = max(last_message, timestamp(record.get("timestamp")))
            if record.get("type") == "session.start":
                details = data.get("context")
                if isinstance(details, dict):
                    cwd = cwd or text(details.get("cwd"))
            elif record.get("type") == "user.message" and not title:
                title = message_text(data.get("content"))
        if cwd:
            yield Session(
                Provider.COPILOT, session_id, title, cwd, last_message or path.stat().st_mtime, home
            )


def read_workspace(path: Path, log: logging.Logger) -> CopilotWorkspace:
    """Use a real YAML parser for quoted paths and multiline CLI session names."""
    if not path.is_file():
        return CopilotWorkspace()
    try:
        import yaml
    except ImportError:
        log.warning("Install PyYAML for Copilot session names: pip install 'PyYAML>=6.0,<7'.")
        return CopilotWorkspace()
    try:
        with path.open("rb") as stream:
            content = stream.read(SAMPLE_BYTES + 1)
        if len(content) > SAMPLE_BYTES:
            return CopilotWorkspace()
        values = yaml.safe_load(content)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log.info("Could not read Copilot workspace metadata: %s", exc)
        return CopilotWorkspace()
    if not isinstance(values, dict):
        return CopilotWorkspace()
    return CopilotWorkspace(
        cwd=text(values.get("cwd")),
        name=text(values.get("name")),
        user_named=values.get("user_named") is True,
    )
