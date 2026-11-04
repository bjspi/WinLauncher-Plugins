"""WinLauncher adapter: settings, search items and the session workflows."""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from winlauncher.plugins.api import (
    Plugin,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    PluginRoute,
)

from .catalog import collect_sessions, session_home
from .domain import Provider, Session, SessionError, SessionSource, visible_sessions
from .exclusions import choose_session, read_exclusions, write_exclusions
from .terminal import resume_session

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DEFAULT_LIMIT = 300
DEFAULT_MAX_AGE_DAYS = 14
MAX_SESSIONS = 2000


class AISessionsPlugin(Plugin):
    """Expose local session workflows through WinLauncher's existing plugin API."""

    id = "ai_sessions"
    label = "AI Session"
    description = (
        "Local Codex, Claude Code and Copilot CLI conversations. "
        "Open a result to resume it in a terminal in its project directory."
    )
    keywords = ("ai", "sessions")
    routes = tuple(PluginRoute(p.value, p.label, (p.value,)) for p in Provider)
    refresh_minutes = 1
    icon = str(ASSETS / "sessions.svg")
    options = (
        PluginOption(
            "limit", "Sessions", DEFAULT_LIMIT, "Maximum visible sessions.", (1, MAX_SESSIONS)
        ),
        PluginOption(
            "max_age_days",
            "Last active within (days)",
            DEFAULT_MAX_AGE_DAYS,
            "Only sessions active within this many days. Zero shows all ages.",
            (0, 3650),
        ),
        PluginOption("codex", "Codex", True),
        PluginOption("claude", "Claude Code", True),
        PluginOption("copilot", "Copilot CLI", True),
        PluginOption("codex_home", "Codex folder", "", "Empty: CODEX_HOME or ~/.codex."),
        PluginOption(
            "claude_home", "Claude Code folder", "", "Empty: CLAUDE_CONFIG_DIR or ~/.claude."
        ),
        PluginOption("copilot_home", "Copilot folder", "", "Empty: COPILOT_HOME or ~/.copilot."),
    )

    def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
        try:
            excluded = read_exclusions(context.data_dir)
            found = current_sessions(context)
            if context.cancel.is_set():
                return []
            visible = visible_sessions(
                found,
                excluded,
                int(context.options["max_age_days"]),
                int(context.options["limit"]),
                time.time(),
            )
            return [session_item(session) for session in visible]
        except SessionError as exc:
            raise PluginError(str(exc)) from exc

    def open(self, item: PluginItem, context: PluginContext) -> None:
        try:
            if item.key in read_exclusions(context.data_dir):
                raise SessionError(
                    "This session is excluded. Restore it in the plugin settings first."
                )
            resume_session(session_from_item(item))
        except SessionError as exc:
            raise PluginError(str(exc)) from exc

    def commands(self) -> tuple[PluginCommand, ...]:
        return (
            PluginCommand("Exclude session…", exclude_session, forgets_items=True),
            PluginCommand("Restore session…", restore_session, forgets_items=True),
        )


def current_sessions(context: PluginContext) -> list[Session]:
    """Translate host settings once; readers have no dependency on the host SDK."""
    sources = [
        SessionSource(
            provider, session_home(provider, str(context.options[f"{provider.value}_home"]))
        )
        for provider in Provider
        if context.options[provider.value]
    ]
    return collect_sessions(sources, context.cancel, context.log)


def session_item(session: Session) -> PluginItem:
    """Name and project are searchable; resume arguments stay in cached data."""
    title = session.display_title
    return PluginItem(
        key=session.key,
        name=title,
        title=f"{session.provider.label}: {title}",
        subtitle=session.cwd,
        keywords=(session.provider.label, session.cwd, session.id),
        icon=str(ASSETS / f"{session.provider.value}.svg"),
        routes=(session.provider.value,),
        data={
            "provider": session.provider.value,
            "id": session.id,
            "cwd": session.cwd,
            "home": str(session.home),
        },
    )


def session_from_item(item: PluginItem) -> Session:
    """Validate cached values before handing them to the terminal boundary."""
    try:
        provider = Provider(item.data.get("provider"))
    except (ValueError, TypeError) as exc:
        raise SessionError("This item does not identify a supported CLI.") from exc
    values = {key: item.data.get(key) for key in ("id", "cwd", "home")}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise SessionError("This session has incomplete resume information. Refresh the plugin.")
    return Session(provider, values["id"], item.name, values["cwd"], 0, Path(values["home"]))


def exclude_session(context: PluginContext) -> str | None:
    """Hide one explicitly chosen session while retaining its conversation files."""
    try:
        excluded = read_exclusions(context.data_dir)
        choices = {
            session.key: session.description
            for session in current_sessions(context)
            if session.key not in excluded
        }
        if not choices:
            return "There are no sessions available to exclude."
        key = choose_session(context.ask, choices, "Exclude session")
        if key is None:
            return None
        excluded[key] = choices[key]
        write_exclusions(context.data_dir, excluded)
        return "Session excluded. Its conversation is kept. Use Restore session to show it again."

    except SessionError as exc:
        raise PluginError(str(exc)) from exc


def restore_session(context: PluginContext) -> str | None:
    """Restore an identity even if its provider is currently disabled or removed."""
    try:
        excluded = read_exclusions(context.data_dir)
        if not excluded:
            return "There are no excluded sessions."
        key = choose_session(context.ask, excluded, "Restore session")
        if key is None:
            return None
        del excluded[key]
        write_exclusions(context.data_dir, excluded)
        return "Session restored. It will appear after the next refresh."

    except SessionError as exc:
        raise PluginError(str(exc)) from exc
