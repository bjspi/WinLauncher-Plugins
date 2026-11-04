"""Claude Code top-level transcripts, titles and message activity."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import message_text, sampled_records, text, timestamp


def claude_sessions(home: Path, cancel: threading.Event) -> Iterator[Session]:
    """Read top-level transcripts only; subagents live in nested subdirectories."""
    for path in (home / "projects").glob("*/*.jsonl"):
        if cancel.is_set():
            return
        if not valid_id(path.stem):
            continue
        session = claude_session(path, home)
        if session is not None:
            yield session


def claude_session(path: Path, home: Path) -> Session | None:
    """Prefer a chosen name over an AI title, then fall back to the first user text."""
    cwd = ""
    first_prompt = ""
    generated_title = ""
    custom_title = ""
    last_message = 0.0
    for record in sampled_records(path):
        if record.get("isSidechain"):
            return None
        cwd = text(record.get("cwd")) or cwd
        kind = record.get("type")
        if kind in ("user", "assistant"):
            last_message = max(last_message, timestamp(record.get("timestamp")))
        if kind == "custom-title":
            custom_title = text(record.get("customTitle"))
        elif kind == "ai-title":
            generated_title = text(record.get("aiTitle"))
        elif kind == "summary":
            generated_title = text(record.get("summary")) or generated_title
        elif kind == "user" and not first_prompt:
            message = record.get("message")
            if isinstance(message, dict):
                first_prompt = message_text(message.get("content"))
    if not cwd:
        return None
    return Session(
        Provider.CLAUDE,
        path.stem,
        custom_title or generated_title or first_prompt,
        cwd,
        last_message or path.stat().st_mtime,
        home,
    )
