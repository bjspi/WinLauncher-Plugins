"""Codex metadata index with a rollout fallback for older installations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import modified_time, plain_path, read_database, sampled_records, text, timestamp

DATABASE_PREFIX = "state_"
TITLE_INDEX_FILE = "session_index.jsonl"
SESSION_META_TYPE = "session_meta"
EXEC_SOURCE = "exec"
SUBAGENT_MARKER = "subagent"


def codex_sessions(home: Path, cancel: threading.Event, log: logging.Logger) -> Iterator[Session]:
    """Use Codex's metadata database, falling back to rollouts on older versions."""
    database = _latest_database(home)
    rows = _thread_rows(database, log) if database else None
    if rows is None:
        yield from _rollout_sessions(home, cancel)
    else:
        yield from _database_sessions(rows, home, cancel)


def _latest_database(home: Path) -> Path | None:
    """The state database of the newest schema; Codex numbers them in the file name."""
    versions = {
        int(path.stem.removeprefix(DATABASE_PREFIX)): path
        for path in home.glob(f"{DATABASE_PREFIX}*.sqlite")
        if path.stem.removeprefix(DATABASE_PREFIX).isdigit()
    }
    return versions[max(versions)] if versions else None


def _thread_rows(database: Path, log: logging.Logger) -> list[sqlite3.Row] | None:
    """Every active thread, or None when the database cannot answer."""
    try:
        columns = {row["name"] for row in read_database(database, "PRAGMA table_info(threads)")}
        title = "COALESCE(NULLIF(name, ''), title)" if "name" in columns else "title"
        return read_database(
            database,
            f"SELECT id, {title} AS title, cwd, updated_at, source, rollout_path FROM threads "
            "WHERE archived = 0 ORDER BY updated_at DESC",
        )
    except sqlite3.Error as exc:
        log.info("Codex metadata unavailable; reading rollouts: %s", exc)
        return None


def _database_sessions(
    rows: list[sqlite3.Row], home: Path, cancel: threading.Event
) -> Iterator[Session]:
    for row in rows:
        if cancel.is_set():
            return
        if not _is_interactive(row["source"]) or not Path(text(row["rollout_path"])).is_file():
            continue
        yield Session(
            Provider.CODEX,
            text(row["id"]),
            text(row["title"]),
            plain_path(text(row["cwd"])),
            timestamp(row["updated_at"]),
            home,
        )


def _rollout_sessions(home: Path, cancel: threading.Event) -> Iterator[Session]:
    titles = _index_titles(home, cancel)
    for path in (home / "sessions").glob("**/*.jsonl"):
        if cancel.is_set():
            return
        payload = _session_metadata(path)
        if payload is None or not _is_interactive(payload.get("source")):
            continue
        session_id = text(payload.get("id")) or text(payload.get("session_id"))
        yield Session(
            Provider.CODEX,
            session_id,
            titles.get(session_id, ""),
            plain_path(text(payload.get("cwd"))),
            modified_time(path),
            home,
        )


def _session_metadata(path: Path) -> dict[str, object] | None:
    for record in sampled_records(path):
        if record.get("type") == SESSION_META_TYPE:
            payload = record.get("payload")
            return payload if isinstance(payload, dict) else None
    return None


def _is_interactive(source: object) -> bool:
    """Batch runs and subagents, whose source is a mapping or its JSON text, don't count."""
    if isinstance(source, dict):
        return False
    return source != EXEC_SOURCE and SUBAGENT_MARKER not in text(source)


def _index_titles(home: Path, cancel: threading.Event) -> dict[str, str]:
    """Read the append-only name index; the latest entry for an id wins."""
    titles: dict[str, str] = {}
    path = home / TITLE_INDEX_FILE
    if not path.is_file():
        return titles
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if cancel.is_set():
                break
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and valid_id(record.get("id")):
                titles[record["id"]] = text(record.get("thread_name"))
    return titles
