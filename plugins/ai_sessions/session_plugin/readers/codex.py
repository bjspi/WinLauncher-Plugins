"""Codex metadata index with a rollout fallback for older installations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import read_database, sampled_records, text, timestamp


def codex_sessions(home: Path, cancel: threading.Event, log: logging.Logger) -> Iterator[Session]:
    """Use Codex's metadata database, falling back to rollouts on older versions."""
    databases = sorted(
        (
            path
            for path in home.glob("state_*.sqlite")
            if path.stem.removeprefix("state_").isdigit()
        ),
        key=lambda path: int(path.stem.removeprefix("state_")),
        reverse=True,
    )
    if databases:
        try:
            columns = {
                row["name"] for row in read_database(databases[0], "PRAGMA table_info(threads)")
            }
            title = "COALESCE(NULLIF(name, ''), title)" if "name" in columns else "title"
            rows = read_database(
                databases[0],
                f"SELECT id, {title} AS title, cwd, updated_at, source, rollout_path FROM threads "
                "WHERE archived = 0 ORDER BY updated_at DESC",
            )
        except sqlite3.Error as exc:
            log.info("Codex metadata unavailable; reading rollouts: %s", exc)
        else:
            for row in rows:
                if cancel.is_set():
                    return
                source = text(row["source"])
                if (
                    source == "exec"
                    or "subagent" in source
                    or not Path(text(row["rollout_path"])).is_file()
                ):
                    continue
                yield Session(
                    Provider.CODEX,
                    text(row["id"]),
                    text(row["title"]),
                    text(row["cwd"]),
                    timestamp(row["updated_at"]),
                    home,
                )
            return
    titles = codex_titles(home, cancel)
    for path in (home / "sessions").glob("**/*.jsonl"):
        if cancel.is_set():
            return
        metadata = next((r for r in sampled_records(path) if r.get("type") == "session_meta"), {})
        payload = metadata.get("payload")
        if not isinstance(payload, dict):
            continue
        source = payload.get("source")
        if source == "exec" or isinstance(source, dict):
            continue
        session_id = text(payload.get("id")) or text(payload.get("session_id"))
        yield Session(
            Provider.CODEX,
            session_id,
            titles.get(session_id, ""),
            text(payload.get("cwd")),
            path.stat().st_mtime,
            home,
        )


def codex_titles(home: Path, cancel: threading.Event) -> dict[str, str]:
    """Read the append-only name index; the latest entry for an id wins."""
    titles = {}
    path = home / "session_index.jsonl"
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
