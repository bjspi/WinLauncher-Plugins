"""WinLauncher adapter: settings, search items and the overview of what was found."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from winlauncher.plugins.api import (
    Plugin,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    SetupRequired,
)

from .catalog import ProfileBookmarks, read_sources
from .discovery import custom_sources, detected_sources
from .domain import Bookmark, ProfileSource, parse_patterns, visible_bookmarks

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIMIT_OPTION = "limit"
EXCLUDED_OPTION = "excluded"
CUSTOM_PATHS_OPTION = "custom_paths"
PROFILE_OPTION_PREFIX = "profile:"
PROFILE_CHOSEN_BY_DEFAULT = False
MAX_LIMIT = 5000  # WinLauncher keeps no more items of one plugin.
SHOWN_PROBLEMS = 3


def _profile_option(source: ProfileSource) -> str:
    return PROFILE_OPTION_PREFIX + source.key


def _profile_toggles() -> tuple[PluginOption, ...]:
    """One switch per profile found now: settings are declared once, when the plugin loads.

    All are off, because bookmarks may be private: nothing is listed until it is chosen.
    A profile created later gets its switch at the next start.
    """
    return tuple(
        PluginOption(_profile_option(source), source.description, PROFILE_CHOSEN_BY_DEFAULT)
        for source in detected_sources()
    )


class BookmarksPlugin(Plugin):
    """Expose the bookmarks of the installed browsers through WinLauncher's plugin API."""

    id = "bookmarks"
    label = "Bookmark"
    description = (
        "The bookmarks of Chrome, Edge, Brave and Firefox, opened in your default browser. "
        "Choose the profiles below. Turn off In every search to see them only behind a keyword."
    )
    keywords = ("bm", "bookmarks")
    icon = str(ASSETS / "bookmarks.svg")
    options = (
        PluginOption(LIMIT_OPTION, "Bookmarks", MAX_LIMIT, "Most at a time.", (1, MAX_LIMIT)),
        PluginOption(
            EXCLUDED_OPTION,
            "Excluded bookmarks",
            "",
            "One fnmatch pattern per line, ignoring case: * ? [abc]. It must fit a whole title, "
            "address or folder name, as in *bank* or https://*.example.com/*.",
            multiline=True,
        ),
        PluginOption(
            CUSTOM_PATHS_OPTION,
            "Custom paths",
            "",
            "One per line, for portable browsers: a profile folder, a User Data folder, or a "
            "bookmark file (Bookmarks, places.sqlite, exported .html).",
            multiline=True,
        ),
        *_profile_toggles(),
    )

    def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
        custom = custom_sources(str(context.options[CUSTOM_PATHS_OPTION]))
        sources = [*_enabled_sources(detected_sources(), context), *custom.sources]
        if not sources:  # SetupRequired also drops what a profile turned off had listed.
            advice = (
                "Choose a browser profile or add a custom path in Settings → Plugins → Bookmarks."
            )
            raise SetupRequired(" ".join((advice, *custom.problems[:SHOWN_PROBLEMS])))
        results = read_sources(sources, context.data_dir, context.cancel)
        if context.cancel.is_set():
            return []
        _report_problems(custom.problems, results, context)
        found = [bookmark for result in results for bookmark in result.bookmarks]
        patterns = parse_patterns(str(context.options[EXCLUDED_OPTION]))
        visible = visible_bookmarks(found, patterns, int(context.options[LIMIT_OPTION]))
        return [bookmark_item(bookmark) for bookmark in visible]

    def commands(self) -> tuple[PluginCommand, ...]:
        return (PluginCommand("Show sources", show_sources),)


def _enabled_sources(
    detected: Iterable[ProfileSource], context: PluginContext
) -> list[ProfileSource]:
    return [
        source
        for source in detected
        if context.options.get(_profile_option(source), PROFILE_CHOSEN_BY_DEFAULT)
    ]


def _report_problems(
    custom_problems: Iterable[str], results: list[ProfileBookmarks], context: PluginContext
) -> None:
    """Fail only when nothing could be read: one broken path must not hide the other browsers."""
    problems = [*custom_problems, *(p for result in results for p in result.problems)]
    for problem in problems:
        context.log.warning("%s", problem)
    if problems and not any(result.any_read for result in results):
        raise PluginError(" ".join(problems[:SHOWN_PROBLEMS]))


def bookmark_item(bookmark: Bookmark) -> PluginItem:
    """Found by title, site and folders; the address itself identifies it across browsers."""
    return PluginItem(
        key=bookmark.url,
        name=bookmark.shown_title,
        target=bookmark.url,
        keywords=tuple(word for word in (bookmark.host, *bookmark.folders) if word),
        breadcrumbs=(bookmark.browser, bookmark.profile, *bookmark.folders),
    )


def show_sources(context: PluginContext) -> str:
    """Tell which browsers and profiles were recognized, and what each one holds."""
    detected = detected_sources()
    custom = custom_sources(str(context.options[CUSTOM_PATHS_OPTION]))
    enabled = _enabled_sources(detected, context)
    results = read_sources([*enabled, *custom.sources], context.data_dir, context.cancel)
    lines = [
        *(_result_line(result) for result in results),
        *(f"{source.description}: not chosen" for source in detected if source not in enabled),
        *custom.problems,
    ]
    return "\n".join(lines) or "No browser profile with bookmarks was found."


def _result_line(result: ProfileBookmarks) -> str:
    if result.problems:
        return "; ".join(result.problems)
    return f"{result.source.description}: {len(result.bookmarks)} bookmarks"
