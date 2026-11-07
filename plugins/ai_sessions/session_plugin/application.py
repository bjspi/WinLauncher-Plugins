"""WinLauncher adapter: settings, search items and the session workflows."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from winlauncher.plugins.api import (
    Chip,
    Choice,
    Plugin,
    PluginAction,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    PluginRoute,
)

from .catalog import collect_sessions, session_home
from .domain import (
    ExclusionRules,
    Provider,
    ResumeTarget,
    Session,
    SessionError,
    SessionSource,
    parse_name_patterns,
    project_folders,
    visible_sessions,
)
from .exclusions import (
    choose_session,
    excluded_folders,
    folder_key,
    read_exclusions,
    write_exclusions,
)
from .terminal import resume_session

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIMIT_OPTION = "limit"
MAX_AGE_OPTION = "max_age_days"
EXCLUDED_NAMES_OPTION = "excluded_names"
DEFAULT_LIMIT = 300
MAX_LIMIT = 2000
DEFAULT_MAX_AGE_DAYS = 14
LONGEST_MAX_AGE_DAYS = 3650
ACTIVITY_DATE_FORMAT = "%Y-%m-%d"
ACTIVITY_TIME_FORMAT = "%H:%M"
NAMED_DAYS_AGO = {0: "Today", 1: "Yesterday"}
FOLDERS_OFFERED = 3  # The project folder and two above it, for Exclude….


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
        PluginOption(
            EXCLUDED_NAMES_OPTION,
            "Excluded session names",
            "",
            "One per line, ignoring case. * and ? are wildcards, as in *probe*.",
            multiline=True,
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
            rules = _exclusion_rules(read_exclusions(context.data_dir), context)
            found = current_sessions(context)
            if context.cancel.is_set():
                return []
            visible = visible_sessions(
                found,
                rules,
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

    def actions(self, item: PluginItem) -> tuple[PluginAction, ...]:
        return (PluginAction("Open project folder", open_project_folder),)

    def exclude(self, item: PluginItem, context: PluginContext) -> bool:
        """This session, or every session of its project folder or a folder above it."""
        with _user_facing_errors():
            cwd = ResumeTarget.from_data(item.data).cwd
            excluded = read_exclusions(context.data_dir)
            choices = [
                Choice(item.key, "Only this session", item.name, checked=True),
                *(
                    Choice(folder_key(folder), "Every session in", folder)
                    for folder in project_folders(cwd, FOLDERS_OFFERED)
                ),
            ]
            ticked = context.choose(
                "Exclude",
                "Ticked ones are left out of the search; Restore session… brings them back. "
                "The conversations themselves are kept.",
                choices,
            )
            if not ticked:
                return False
            for choice in choices:
                if choice.key in ticked:
                    excluded[choice.key] = _exclusion_description(choice, item)
            write_exclusions(context.data_dir, excluded)
            return True

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


def _exclusion_rules(excluded: Mapping[str, str], context: PluginContext) -> ExclusionRules:
    patterns = parse_name_patterns(str(context.options[EXCLUDED_NAMES_OPTION]))
    return ExclusionRules(excluded.keys(), patterns, excluded_folders(excluded))


def open_project_folder(item: PluginItem, context: PluginContext) -> None:
    """The folder the session works in, in Explorer."""
    with _user_facing_errors():
        cwd = Path(ResumeTarget.from_data(item.data).cwd)
    if not cwd.is_dir():
        raise PluginError(f"The project folder no longer exists: {cwd}")
    os.startfile(cwd)  # noqa: S606 - a folder the session itself recorded.


def _exclusion_description(choice: Choice, item: PluginItem) -> str:
    """What Restore session… shows for an exclusion, and finds it by."""
    if choice.key == item.key:
        return f"{item.title} · {item.subtitle}"
    return f"Every session in {choice.detail}"


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
        rules = _exclusion_rules(excluded, context)
        choices = {
            session.key: session.description
            for session in current_sessions(context)
            if not rules.hides(session)
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
