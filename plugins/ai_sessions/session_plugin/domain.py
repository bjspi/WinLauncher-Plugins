"""Session identity and visibility policy, independent of WinLauncher and storage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

TITLE_LENGTH = 160
SECONDS_PER_DAY = 24 * 60 * 60


class SessionError(Exception):
    """An operation that could not complete, with a message suitable for the user."""


class Provider(StrEnum):
    """Stable route ids and executable names of the supported CLIs."""

    CODEX = "codex"
    CLAUDE = "claude"
    COPILOT = "copilot"

    @property
    def label(self) -> str:
        return {
            Provider.CODEX: "Codex",
            Provider.CLAUDE: "Claude Code",
            Provider.COPILOT: "Copilot",
        }[self]

    @property
    def home_variable(self) -> str:
        return {
            Provider.CODEX: "CODEX_HOME",
            Provider.CLAUDE: "CLAUDE_CONFIG_DIR",
            Provider.COPILOT: "COPILOT_HOME",
        }[self]


@dataclass(frozen=True, slots=True)
class Session:
    """Only the metadata needed for searching and resuming one conversation."""

    provider: Provider
    id: str
    title: str
    cwd: str
    updated: float
    home: Path

    @property
    def key(self) -> str:
        return f"{self.provider.value}:{self.id}"

    @property
    def display_title(self) -> str:
        return compact_title(self.title) or f"Session {self.id}"

    @property
    def description(self) -> str:
        return f"{self.provider.label}: {self.display_title} · {self.cwd}"


@dataclass(frozen=True, slots=True)
class SessionSource:
    """One enabled provider and its actual configuration directory."""

    provider: Provider
    home: Path


def valid_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def compact_title(value: str) -> str:
    return " ".join(value.split())[:TITLE_LENGTH]


def visible_sessions(
    sessions: Iterable[Session],
    excluded: Mapping[str, str],
    max_age_days: int,
    limit: int,
    now: float,
) -> list[Session]:
    """Apply exclusions and the age window before the count limit, newest first."""
    cutoff = now - max_age_days * SECONDS_PER_DAY if max_age_days else 0
    visible = []
    for session in sorted(sessions, key=lambda session: session.updated, reverse=True):
        if session.key in excluded or session.updated < cutoff:
            continue
        visible.append(session)
        if len(visible) >= limit:
            break
    return visible
