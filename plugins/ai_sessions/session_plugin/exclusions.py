"""Persist reversible exclusions by stable identity and select them explicitly."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from .domain import SessionError

EXCLUSIONS_FILE = "excluded-sessions.json"
# The host's question dialog has a fixed width, wraps its text and cannot scroll: a list
# longer than this, or lines that wrap, could push its buttons off the screen.
CHOICE_LIMIT = 8
CHOICE_LINE_START = 30
CHOICE_LINE_END = 18  # Keeps the project at the end of a session's description in view.

Ask = Callable[[str, str], str | None]


def read_exclusions(folder: Path) -> dict[str, str]:
    """Fail visibly on damage so previously excluded conversations stay hidden."""
    path = folder / EXCLUSIONS_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SessionError(f"Could not read excluded sessions: {exc}") from exc
    if not isinstance(saved, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in saved.items()
    ):
        raise SessionError("The excluded sessions file must map session keys to titles.")
    return saved


def write_exclusions(folder: Path, excluded: Mapping[str, str]) -> None:
    """Replace atomically so an interrupted write cannot truncate the filter."""
    path = folder / EXCLUSIONS_FILE
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(excluded, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise SessionError(f"Could not save excluded sessions: {exc}") from exc


def choose_session(ask: Ask, choices: Mapping[str, str], title: str) -> str | None:
    """Search first, then explicitly select one session; never hide a fuzzy match."""
    query = ask(title, "Search by session title, project, provider or session ID:")
    if not query or not query.strip():
        return None
    matches = _matching_keys(choices, query)
    if not matches:
        raise SessionError("No matching session found.")
    if len(matches) > CHOICE_LIMIT:
        raise SessionError("Too many matching sessions. Search with a more specific title or ID.")
    lines = [f"{index}. {_shortened(choices[key])}" for index, key in enumerate(matches, start=1)]
    answer = ask(title, "\n".join(lines) + "\n\nEnter the number of the session:")
    if not answer:
        return None
    return matches[_chosen_index(answer, len(matches))]


def _matching_keys(choices: Mapping[str, str], query: str) -> list[str]:
    terms = query.casefold().split()
    return [
        key
        for key, label in choices.items()
        if all(term in f"{key} {label}".casefold() for term in terms)
    ]


def _shortened(label: str) -> str:
    """Fit one dialog line, keeping both the title's start and the project's end."""
    if len(label) <= CHOICE_LINE_START + CHOICE_LINE_END:
        return label
    return f"{label[:CHOICE_LINE_START]}…{label[-CHOICE_LINE_END:]}"


def _chosen_index(answer: str, count: int) -> int:
    """Translate the one-based number the user saw into a list index."""
    try:
        number = int(answer.strip())
    except ValueError:
        number = 0
    if not 1 <= number <= count:
        raise SessionError("Enter one of the session numbers shown.")
    return number - 1
