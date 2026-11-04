"""Gather local metadata through the independent provider adapters."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path

from .domain import Provider, Session, SessionSource, valid_id
from .readers.claude import claude_sessions
from .readers.codex import codex_sessions
from .readers.copilot import copilot_sessions


def session_home(provider: Provider, configured: str) -> Path:
    """Resolve an explicit setting before the CLI's environment and profile default."""
    location = configured.strip() or os.environ.get(provider.home_variable)
    return Path(location).expanduser().resolve() if location else Path.home() / f".{provider.value}"


def collect_sessions(
    sources: Iterable[SessionSource], cancel: threading.Event, log: logging.Logger
) -> list[Session]:
    """Keep one broken provider from hiding sessions belonging to another."""
    sessions: dict[str, Session] = {}
    for source in sources:
        provider = source.provider
        if cancel.is_set():
            break
        home = source.home
        try:
            if provider == Provider.CODEX:
                found = codex_sessions(home, cancel, log)
            elif provider == Provider.CLAUDE:
                found = claude_sessions(home, cancel)
            else:
                found = copilot_sessions(home, cancel, log)
            for session in found:
                if valid_id(session.id) and session.cwd:
                    sessions[session.key] = session
        except (OSError, sqlite3.Error) as exc:
            log.warning("Could not read %s sessions: %s", provider.label, exc)
    return sorted(sessions.values(), key=lambda session: session.updated, reverse=True)
