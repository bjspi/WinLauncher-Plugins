"""GitHub Copilot CLI local summaries and event metadata."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import (
    SAMPLE_BYTES,
    message_text,
    modified_time,
    read_database,
    sampled_records,
    text,
    timestamp,
)

try:
    import yaml
except ImportError:  # Declared in plugin.toml; without it, session names are just less exact.
    yaml = None

SUMMARY_DATABASE = "session-store.db"
WORKSPACE_FILE = "workspace.yaml"
USER_MESSAGE = "user.message"
MESSAGE_TYPES = (USER_MESSAGE, "assistant.message")
SESSION_START = "session.start"


@dataclass(frozen=True, slots=True)
class CopilotWorkspace:
    """The latest CLI metadata, including a name explicitly chosen by the user."""

    cwd: str = ""
    name: str = ""
    user_named: bool = False


def copilot_sessions(home: Path, cancel: threading.Event, log: logging.Logger) -> Iterator[Session]:
    """Only local CLI sessions with an events file can be resumed this way."""
    if yaml is None:
        log.warning("Install PyYAML for Copilot session names: pip install 'PyYAML>=6.0,<7'.")
    summaries = _saved_summaries(home / SUMMARY_DATABASE, log)
    for path in (home / "session-state").glob("*/events.jsonl"):
        if cancel.is_set():
            return
        if not valid_id(path.parent.name):
            continue
        session = _copilot_session(path, home, summaries, log)
        if session is not None:
            yield session


def _saved_summaries(database: Path, log: logging.Logger) -> dict[str, str]:
    if not database.is_file():
        return {}
    try:
        rows = read_database(database, "SELECT id, summary FROM sessions")
    except sqlite3.Error as exc:
        log.info("Copilot metadata unavailable; reading events: %s", exc)
        return {}
    return {text(row["id"]): text(row["summary"]) for row in rows}


def _copilot_session(
    path: Path, home: Path, summaries: dict[str, str], log: logging.Logger
) -> Session | None:
    """Prefer a chosen name, then the saved summary, workspace name and first prompt."""
    session_id = path.parent.name
    workspace = _read_workspace(path.with_name(WORKSPACE_FILE), log)
    cwd = workspace.cwd
    chosen_name = workspace.name if workspace.user_named else ""
    title = chosen_name or summaries.get(session_id) or workspace.name
    last_message = 0.0
    for record in sampled_records(path):
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        kind = record.get("type")
        if kind in MESSAGE_TYPES:
            last_message = max(last_message, timestamp(record.get("timestamp")))
        if kind == SESSION_START:
            cwd = cwd or _start_folder(data)
        elif kind == USER_MESSAGE and not title:
            title = message_text(data.get("content"))
    if not cwd:
        return None
    return Session(
        Provider.COPILOT, session_id, title, cwd, last_message or modified_time(path), home
    )


def _start_folder(data: dict[str, object]) -> str:
    context = data.get("context")
    return text(context.get("cwd")) if isinstance(context, dict) else ""


def _read_workspace(path: Path, log: logging.Logger) -> CopilotWorkspace:
    """Use a real YAML parser for quoted paths and multiline CLI session names."""
    if yaml is None or not path.is_file():
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
