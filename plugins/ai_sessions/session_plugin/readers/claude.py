"""Claude Code top-level transcripts, titles and message activity."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path

from ..domain import Provider, Session, valid_id
from .records import message_text, modified_time, sampled_records, text, timestamp

MESSAGE_TYPES = ("user", "assistant")
# `claude -p` and the Agent SDK record entrypoints such as "sdk-cli": no conversation
# a person had, the counterpart of Codex's `exec`.
NON_INTERACTIVE_ENTRYPOINT_PREFIX = "sdk"
# What Claude Code stores as user text when someone runs a slash command.
COMMAND_MARKUP = ("<local-command-", "<command-")


def claude_sessions(home: Path, cancel: threading.Event, log: logging.Logger) -> Iterator[Session]:
    """Read top-level transcripts only; subagents live in nested subdirectories.

    `log` belongs to the signature all readers share; this format has nothing to report.
    """
    for path in (home / "projects").glob("*/*.jsonl"):
        if cancel.is_set():
            return
        if not valid_id(path.stem):
            continue
        session = _claude_session(path, home)
        if session is not None:
            yield session


def _claude_session(path: Path, home: Path) -> Session | None:
    """Prefer a chosen name over an AI title, then fall back to the first user text.

    Sidechains and non-interactive runs are not conversations to return to, and a
    transcript without any message has nothing to resume.
    """
    cwd = ""
    first_prompt = ""
    generated_title = ""
    custom_title = ""
    has_message = False
    last_message = 0.0
    for record in sampled_records(path):
        if record.get("isSidechain") or _is_non_interactive(record):
            return None
        cwd = text(record.get("cwd")) or cwd
        kind = record.get("type")
        if kind in MESSAGE_TYPES:
            has_message = True
            last_message = max(last_message, timestamp(record.get("timestamp")))
        if kind == "custom-title":
            custom_title = text(record.get("customTitle"))
        elif kind == "ai-title":
            generated_title = text(record.get("aiTitle"))
        elif kind == "summary":
            generated_title = text(record.get("summary")) or generated_title
        elif kind == "user" and not first_prompt:
            first_prompt = _typed_prompt(record)
    if not cwd or not has_message:
        return None
    return Session(
        Provider.CLAUDE,
        path.stem,
        custom_title or generated_title or first_prompt,
        cwd,
        last_message or modified_time(path),
        home,
    )


def _is_non_interactive(record: dict[str, object]) -> bool:
    return text(record.get("entrypoint")).startswith(NON_INTERACTIVE_ENTRYPOINT_PREFIX)


def _typed_prompt(record: dict[str, object]) -> str:
    """What the user wrote, leaving out injected context and slash-command markup."""
    message = record.get("message")
    if record.get("isMeta") or not isinstance(message, dict):
        return ""
    prompt = message_text(message.get("content"))
    return "" if prompt.lstrip().startswith(COMMAND_MARKUP) else prompt
