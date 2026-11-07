"""Read every chosen source, keeping one unreadable store from hiding the others.

Icons are a bonus: a profile whose icon cache cannot be read still lists its bookmarks.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .domain import Bookmark, BookmarkError, BookmarkStore, ProfileSource, StoreFormat
from .readers.chromium import read_chromium_bookmarks
from .readers.favicons import SiteIcons, read_favicons
from .readers.firefox import read_firefox_places
from .readers.html_export import read_html_export


@dataclass(frozen=True, slots=True)
class ProfileBookmarks:
    """What one source held, and what could not be read of it."""

    source: ProfileSource
    bookmarks: tuple[Bookmark, ...]
    problems: tuple[str, ...]
    icon_problem: str = ""

    @property
    def any_read(self) -> bool:
        """Whether a store could be read at all, even if it holds no bookmarks."""
        return len(self.problems) < len(self.source.stores)


def read_sources(
    sources: Iterable[ProfileSource], work_dir: Path, cancel: threading.Event
) -> list[ProfileBookmarks]:
    """Read source after source; a cancelled run returns what it has so far."""
    results = []
    for source in sources:
        if cancel.is_set():
            break
        results.append(_read_source(source, work_dir))
    return results


def _read_source(source: ProfileSource, work_dir: Path) -> ProfileBookmarks:
    bookmarks: list[Bookmark] = []
    problems: list[str] = []
    for store in source.stores:
        try:
            found = _read_store(store, work_dir)
        except BookmarkError as exc:
            problems.append(f"{source.description}: {exc}")
            continue
        except Exception as exc:  # A foreign file may fail in ways no reader foresees.
            problems.append(f"{source.description}: {store.path.name} is unusable: {exc!r}")
            continue
        bookmarks.extend(replace(b, browser=source.browser, profile=source.profile) for b in found)
    icons, icon_problem = _read_icons(source, bookmarks, work_dir)
    with_icons = tuple(replace(b, icon=icons.for_url(b.url)) for b in bookmarks)
    return ProfileBookmarks(source, with_icons, tuple(problems), icon_problem)


def _read_icons(
    source: ProfileSource, bookmarks: list[Bookmark], work_dir: Path
) -> tuple[SiteIcons, str]:
    """The cached icons of the profile's bookmarks, and why there are none, if they failed."""
    if source.icons is None or not bookmarks:
        return SiteIcons(), ""
    try:
        return read_favicons(source.icons, work_dir, {b.url for b in bookmarks}), ""
    except BookmarkError as exc:
        return SiteIcons(), f"{source.description}: no icons, {exc}"
    except Exception as exc:  # A foreign file may fail in ways no reader foresees.
        return SiteIcons(), f"{source.description}: no icons, {source.icons.path.name}: {exc!r}"


def _read_store(store: BookmarkStore, work_dir: Path) -> list[Bookmark]:
    match store.format:
        case StoreFormat.CHROMIUM_JSON:
            return read_chromium_bookmarks(store.path)
        case StoreFormat.FIREFOX_PLACES:
            return read_firefox_places(store.path, work_dir)
        case StoreFormat.HTML_EXPORT:
            return read_html_export(store.path)
