"""What a bookmark is and which ones to show, independent of WinLauncher and storage."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import urlsplit

# A bookmark is handed to Windows, which would run any registered scheme and start any
# program a file: address names, even on a network share. Bookmarklets and browser pages
# such as javascript:, place: or chrome: cannot be opened from outside a browser anyway.
OPENABLE_SCHEMES = frozenset({"http", "https", "ftp"})
WWW_PREFIX = "www."
ELLIPSIS = "…"


class BookmarkError(Exception):
    """A store that could not be read, with a message suitable for the user."""


class StoreFormat(StrEnum):
    CHROMIUM_JSON = "chromium-json"
    FIREFOX_PLACES = "firefox-places"
    HTML_EXPORT = "html-export"


@dataclass(frozen=True, slots=True)
class BookmarkStore:
    """One file holding bookmarks."""

    path: Path
    format: StoreFormat


class IconFormat(StrEnum):
    CHROMIUM_FAVICONS = "chromium-favicons"
    FIREFOX_FAVICONS = "firefox-favicons"


@dataclass(frozen=True, slots=True)
class IconStore:
    """The database in which a browser caches the icons of the sites it showed."""

    path: Path
    format: IconFormat


@dataclass(frozen=True, slots=True)
class IconImage:
    """A site's icon as the browser cached it: an image file's bytes."""

    data: bytes = field(repr=False)
    width: int  # In pixels; Firefox stores an SVG icon with a width of its own.


@dataclass(frozen=True, slots=True)
class ProfileSource:
    """A browser profile, or a path the user named, and the stores it reads."""

    key: str  # Stable across restarts: the settings toggle of a detected profile hangs on it.
    browser: str
    profile: str
    stores: tuple[BookmarkStore, ...]
    icons: IconStore | None = None

    @property
    def description(self) -> str:
        return f"{self.browser} · {self.profile}"


@dataclass(frozen=True, slots=True)
class Bookmark:
    title: str  # May be empty: a browser allows bookmarks without a name.
    url: str
    folders: tuple[str, ...] = ()  # Outermost first.
    recency: float = 0.0  # Seconds since 1970: last visit or, without one, when it was added.
    browser: str = ""
    profile: str = ""
    icon: IconImage | None = None

    @property
    def shown_title(self) -> str:
        return self.title or self.url

    @property
    def host(self) -> str:
        """The site, by which a bookmark is found too."""
        return site_of(self.url)

    @property
    def short_address(self) -> str:
        """Where it leads, at a glance: the site and the first part of the path."""
        try:
            path = urlsplit(self.url).path
        except ValueError:
            return self.host
        first, _, rest = path.strip("/").partition("/")
        if not first:
            return self.host
        return f"{self.host}/{first}/{ELLIPSIS}" if rest else f"{self.host}/{first}"


def site_of(url: str) -> str:
    """The host of an address without its `www.`; empty for one that names none."""
    try:
        return (urlsplit(url).hostname or "").removeprefix(WWW_PREFIX)
    except ValueError:
        return ""


def tidy(text: object) -> str:
    """Foreign text as one line; anything but text counts as empty."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def inside(folders: tuple[str, ...], name: object) -> tuple[str, ...]:
    """The location of a folder called `name`; an unnamed folder adds no part."""
    tidied = tidy(name)
    return (*folders, tidied) if tidied else folders


def parse_patterns(text: str) -> tuple[str, ...]:
    """Exclusion patterns of a multiline setting, one per line, ignoring case."""
    return tuple(line.strip().casefold() for line in text.splitlines() if line.strip())


def is_openable(url: str) -> bool:
    try:
        return urlsplit(url).scheme.lower() in OPENABLE_SCHEMES
    except ValueError:
        return False


def is_excluded(bookmark: Bookmark, patterns: tuple[str, ...]) -> bool:
    """Whether a pattern fits its title, its address, or a folder it lies in, at any depth."""
    names = (bookmark.title, bookmark.url, *bookmark.folders)
    return any(fnmatchcase(name.casefold(), pattern) for name in names for pattern in patterns)


def visible_bookmarks(
    found: Iterable[Bookmark], patterns: tuple[str, ...], limit: int
) -> list[Bookmark]:
    """Most recently used first, one row per address, whichever browser it was saved in."""
    wanted = (b for b in found if is_openable(b.url) and not is_excluded(b, patterns))
    by_recency = sorted(wanted, key=lambda bookmark: bookmark.recency, reverse=True)
    by_address: dict[str, Bookmark] = {}
    for bookmark in by_recency:
        by_address.setdefault(bookmark.url, bookmark)
    return list(by_address.values())[:limit]
