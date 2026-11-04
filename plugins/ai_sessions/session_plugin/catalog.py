"""Gather local metadata through the independent provider adapters."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from .domain import Provider, Session, SessionSource, valid_id
from .readers.claude import claude_sessions
from .readers.codex import codex_sessions
from .readers.copilot import copilot_sessions

SessionReader = Callable[[Path, threading.Event, logging.Logger], Iterator[Session]]

READERS: dict[Provider, SessionReader] = {
    Provider.CODEX: codex_sessions,
    Provider.CLAUDE: claude_sessions,
    Provider.COPILOT: copilot_sessions,
}


def session_home(provider: Provider, configured: str) -> Path:
    """Resolve an explicit setting before the CLI's environment and profile default."""
    location = configured.strip() or os.environ.get(provider.home_variable)
    return Path(location).expanduser().resolve() if location else provider.default_home


def collect_sessions(
    sources: Iterable[SessionSource], cancel: threading.Event, log: logging.Logger
) -> list[Session]:
    """Every resumable session of the given sources, newest first."""
    sessions: dict[str, Session] = {}
    for source in sources:
        if cancel.is_set():
            break
        for session in _readable_sessions(source, cancel, log):
            if valid_id(session.id) and session.cwd:
                sessions[session.key] = session
    return sorted(sessions.values(), key=lambda session: session.updated, reverse=True)


def _readable_sessions(
    source: SessionSource, cancel: threading.Event, log: logging.Logger
) -> Iterator[Session]:
    """Keep one broken provider from hiding sessions belonging to another."""
    try:
        yield from READERS[source.provider](source.home, cancel, log)
    except (OSError, sqlite3.Error) as exc:
        log.warning("Could not read %s sessions: %s", source.provider.label, exc)
