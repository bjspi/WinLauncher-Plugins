"""WinLauncher adapter: settings, search items and the session workflows."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from winlauncher.plugins.api import (
    Chip,
    Plugin,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    PluginRoute,
)

from .catalog import collect_sessions, session_home
from .domain import Provider, ResumeTarget, Session, SessionError, SessionSource, visible_sessions
from .exclusions import choose_session, read_exclusions, write_exclusions
from .terminal import resume_session

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIMIT_OPTION = "limit"
MAX_AGE_OPTION = "max_age_days"
DEFAULT_LIMIT = 300
MAX_LIMIT = 2000
DEFAULT_MAX_AGE_DAYS = 14
LONGEST_MAX_AGE_DAYS = 3650
ACTIVITY_DATE_FORMAT = "%Y-%m-%d"
ACTIVITY_TIME_FORMAT = "%H:%M"
NAMED_DAYS_AGO = {0: "Today", 1: "Yesterday"}


def _home_option(provider: Provider) -> str:
    return f"{provider.value}_home"


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
            LIMIT_OPTION, "Sessions", DEFAULT_LIMIT, "Maximum visible sessions.", (1, MAX_LIMIT)
        ),
        PluginOption(
            MAX_AGE_OPTION,
            "Last active within (days)",
            DEFAULT_MAX_AGE_DAYS,
            "Only sessions active within this many days. Zero shows all ages.",
            (0, LONGEST_MAX_AGE_DAYS),
        ),
        *(PluginOption(p.value, p.label, True) for p in Provider),
        *(
            PluginOption(
                _home_option(p),
                f"{p.label} folder",
                "",
                f"Empty: {p.home_variable} or ~/.{p.value}.",
            )
            for p in Provider
        ),
    )

    def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
        with _user_facing_errors():
            excluded = read_exclusions(context.data_dir)
            found = current_sessions(context)
            if context.cancel.is_set():
                return []
            visible = visible_sessions(
                found,
                excluded,
                int(context.options[MAX_AGE_OPTION]),
                int(context.options[LIMIT_OPTION]),
                time.time(),
            )
            return [session_item(session) for session in visible]

    def open(self, item: PluginItem, context: PluginContext) -> None:
        with _user_facing_errors():
            if item.key in read_exclusions(context.data_dir):
                raise SessionError(
                    "This session is excluded. Restore it in the plugin settings first."
                )
            resume_session(ResumeTarget.from_data(item.data))

    def commands(self) -> tuple[PluginCommand, ...]:
        return (
            PluginCommand("Exclude session…", exclude_session, forgets_items=True),
            PluginCommand("Restore session…", restore_session, forgets_items=True),
        )


@contextmanager
def _user_facing_errors() -> Iterator[None]:
    """Translate at the host boundary, so the inner modules stay free of its SDK."""
    try:
        yield
    except SessionError as exc:
        raise PluginError(str(exc)) from exc


def current_sessions(context: PluginContext) -> list[Session]:
    """Translate host settings once; readers have no dependency on the host SDK."""
    sources = [
        SessionSource(
            provider, session_home(provider, str(context.options[_home_option(provider)]))
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
        data=session.resume_target.as_data(),
        chips=_activity_chips(session.updated),
    )


def _activity_chips(updated: float) -> tuple[Chip, ...]:
    """The last activity in local time; an absurd value from a foreign file shows no chip."""
    if not updated:
        return ()
    try:
        moment = datetime.fromtimestamp(updated)
    except (OverflowError, OSError, ValueError):
        return ()
    return (Chip(activity_label(moment, date.today())),)


def activity_label(moment: datetime, today: date) -> str:
    """Name today and yesterday; the frequent refresh keeps the names current."""
    days_ago = (today - moment.date()).days
    day = NAMED_DAYS_AGO.get(days_ago) or moment.strftime(ACTIVITY_DATE_FORMAT)
    return f"{day} {moment.strftime(ACTIVITY_TIME_FORMAT)}"


def exclude_session(context: PluginContext) -> str | None:
    """Hide one explicitly chosen session while retaining its conversation files."""
    with _user_facing_errors():
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


def restore_session(context: PluginContext) -> str | None:
    """Restore an identity even if its provider is currently disabled or removed."""
    with _user_facing_errors():
        excluded = read_exclusions(context.data_dir)
        if not excluded:
            return "There are no excluded sessions."
        key = choose_session(context.ask, excluded, "Restore session")
        if key is None:
            return None
        del excluded[key]
        write_exclusions(context.data_dir, excluded)
        return "Session restored. It will appear after the next refresh."
