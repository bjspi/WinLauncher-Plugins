"""Persist reversible exclusions by stable identity and select them explicitly."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .domain import SessionError

EXCLUSIONS_FILE = "excluded-sessions.json"
CHOICE_LIMIT = 20


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


def write_exclusions(folder: Path, excluded: dict[str, str]) -> None:
    """Replace atomically so an interrupted write cannot truncate the filter."""
    path = folder / EXCLUSIONS_FILE
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(excluded, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise SessionError(f"Could not save excluded sessions: {exc}") from exc


def choose_session(
    ask: Callable[[str, str], str | None], choices: dict[str, str], title: str
) -> str | None:
    """Search first, then explicitly select one session; never hide a fuzzy match."""
    query = ask(title, "Search by session title, project, provider or session ID:")
    if not query or not query.strip():
        return None
    terms = query.casefold().split()
    matches = [
        key
        for key, label in choices.items()
        if all(term in f"{key} {label}".casefold() for term in terms)
    ]
    if not matches:
        raise SessionError("No matching session found.")
    if len(matches) > CHOICE_LIMIT:
        raise SessionError("Too many matching sessions. Search with a more specific title or ID.")
    lines = [f"{index}. {choices[key]} [{key}]" for index, key in enumerate(matches, start=1)]
    answer = ask(title, "\n".join(lines) + "\n\nEnter the number of the session:")
    if not answer:
        return None
    try:
        number = int(answer.strip())
    except ValueError as exc:
        raise SessionError("Enter one of the session numbers shown.") from exc
    if not 1 <= number <= len(matches):
        raise SessionError("Enter one of the session numbers shown.")
    return matches[number - 1]
