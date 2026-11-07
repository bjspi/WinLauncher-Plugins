"""Session identity and visibility policy, independent of WinLauncher and storage."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path, PureWindowsPath
from typing import TypeGuard
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
            Provider.COPILOT: "Copilot CLI",
        }[self]

    @property
    def home_variable(self) -> str:
        return {
            Provider.CODEX: "CODEX_HOME",
            Provider.CLAUDE: "CLAUDE_CONFIG_DIR",
            Provider.COPILOT: "COPILOT_HOME",
        }[self]

    @property
    def default_home(self) -> Path:
        """Where the CLI keeps its data unless a setting or its variable says otherwise."""
        return (Path.home() / f".{self.value}").resolve()


@dataclass(frozen=True, slots=True)
class ResumeTarget:
    """What reopening a conversation needs; it survives in the host's item cache."""

    provider: Provider
    id: str
    cwd: str
    home: Path

    def as_data(self) -> dict[str, str]:
        """The JSON values stored with a search item."""
        return {
            "provider": self.provider.value,
            "id": self.id,
            "cwd": self.cwd,
            "home": str(self.home),
        }

    @classmethod
    def from_data(cls, data: Mapping[str, object]) -> ResumeTarget:
        """Reject cached values that do not describe a resumable session."""
        try:
            provider = Provider(data.get("provider"))
        except ValueError as exc:
            raise SessionError("This item does not identify a supported CLI.") from exc
        session_id, cwd, home = data.get("id"), data.get("cwd"), data.get("home")
        if not valid_id(session_id):
            raise SessionError("This item has an invalid session ID.")
        if not (isinstance(cwd, str) and cwd and isinstance(home, str) and home):
            raise SessionError(
                "This session has incomplete resume information. Refresh the plugin."
            )
        return cls(provider, session_id, cwd, Path(home))


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

    @property
    def resume_target(self) -> ResumeTarget:
        return ResumeTarget(self.provider, self.id, self.cwd, self.home)


@dataclass(frozen=True, slots=True)
class ExclusionRules:
    """Which sessions stay hidden: chosen ones, those of chosen project folders, and
    names matching a pattern."""

    keys: Collection[str] = ()
    name_patterns: tuple[str, ...] = ()  # Casefolded, as `parse_name_patterns` returns them.
    folders: tuple[str, ...] = ()  # Every session started in or below one is hidden.

    def hides(self, session: Session) -> bool:
        if session.key in self.keys:
            return True
        if any(is_within_folder(session.cwd, folder) for folder in self.folders):
            return True
        name = session.display_title.casefold()
        return any(fnmatchcase(name, pattern) for pattern in self.name_patterns)


def is_within_folder(path: str, folder: str) -> bool:
    """Whether `path` is `folder` or below it, as Windows compares paths: ignoring case
    and the kind of slash."""
    if not path or not folder:
        return False
    inner, outer = PureWindowsPath(path.casefold()), PureWindowsPath(folder.casefold())
    return inner == outer or outer in inner.parents


def project_folders(cwd: str, depth: int) -> tuple[str, ...]:
    """`cwd` and up to `depth - 1` folders above it, nearest first, never a drive root:
    excluding a whole drive is not a sensible single choice."""
    if not cwd:
        return ()
    folders = []
    current = PureWindowsPath(cwd)
    while current.parent != current and len(folders) < depth:
        folders.append(str(current))
        current = current.parent
    return tuple(folders)


def parse_name_patterns(lines: str) -> tuple[str, ...]:
    """One fnmatch pattern per line, ignoring case; blank lines mean nothing."""
    stripped = (line.strip() for line in lines.splitlines())
    return tuple(line.casefold() for line in stripped if line)


@dataclass(frozen=True, slots=True)
class SessionSource:
    """One enabled provider and its actual configuration directory."""

    provider: Provider
    home: Path


def valid_id(value: object) -> TypeGuard[str]:
    """Only a canonical UUID may become a command-line argument."""
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def compact_title(value: str) -> str:
    return " ".join(value.split())[:TITLE_LENGTH]


def visible_sessions(
    newest_first: Iterable[Session],
    rules: ExclusionRules,
    max_age_days: int,
    limit: int,
    now: float,
) -> list[Session]:
    """Apply exclusions and the age window before the count limit."""
    cutoff = now - max_age_days * SECONDS_PER_DAY if max_age_days else 0
    visible = [
        session
        for session in newest_first
        if session.updated >= cutoff and not rules.hides(session)
    ]
    return visible[:limit]
