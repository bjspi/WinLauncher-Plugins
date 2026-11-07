"""Find the bookmark stores: browser profiles in their standard places and custom paths."""

from __future__ import annotations

import configparser
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .domain import BookmarkError, BookmarkStore, ProfileSource, StoreFormat, tidy

CHROME_DATA = Path("Google", "Chrome", "User Data")
EDGE_DATA = Path("Microsoft", "Edge", "User Data")
BRAVE_DATA = Path("BraveSoftware", "Brave-Browser", "User Data")
FIREFOX_DATA = Path("Mozilla", "Firefox")
# Firefox from the Microsoft Store keeps its data inside its package.
FIREFOX_STORE_DATA = "Packages/Mozilla.Firefox_*/LocalCache/Roaming/Mozilla/Firefox"

LOCAL_STATE = "Local State"
DEFAULT_PROFILE = "Default"
NUMBERED_PROFILES = "Profile *"
# A Chromium profile keeps local bookmarks in the first file and those of the signed-in
# account in the second; a signed-in Chrome may have only the second one. The
# Encrypted* files beside them hold the same bookmarks and cannot be read.
CHROMIUM_FILES = ("Bookmarks", "AccountBookmarks")

PROFILES_INI = "profiles.ini"
PROFILES_FOLDER = "Profiles"
PLACES = "places.sqlite"
HTML_SUFFIXES = frozenset({".html", ".htm"})
SQLITE_SUFFIX = ".sqlite"

CUSTOM_CHROMIUM = "Chromium"
CUSTOM_FIREFOX = "Firefox"
CUSTOM_HTML = "HTML export"


@dataclass(frozen=True, slots=True)
class CustomSources:
    """What the user's custom paths lead to, and why some lead nowhere."""

    sources: tuple[ProfileSource, ...]
    problems: tuple[str, ...]


def detected_sources() -> list[ProfileSource]:
    """Every profile with bookmarks in the standard folders of this Windows user.

    A browser counts as present when it left a profile here. Its registered program
    would say less: it misses per-user and Store installations, and what can be read
    is what matters.
    """
    local = _user_folder("LOCALAPPDATA", Path("AppData", "Local"))
    roaming = _user_folder("APPDATA", Path("AppData", "Roaming"))
    return [
        *chromium_sources(local / CHROME_DATA, "Chrome", "chrome"),
        *chromium_sources(local / EDGE_DATA, "Edge", "edge"),
        *chromium_sources(local / BRAVE_DATA, "Brave", "brave"),
        *firefox_sources(roaming / FIREFOX_DATA, "Firefox"),
        *(
            source
            for store_data in sorted(local.glob(FIREFOX_STORE_DATA))
            for source in firefox_sources(store_data, "Firefox")
        ),
    ]


def custom_sources(text: str) -> CustomSources:
    """The multiline setting: one profile folder, data folder or bookmark file per line."""
    sources: list[ProfileSource] = []
    problems: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        path = Path(os.path.expandvars(line.strip().strip('"'))).expanduser()
        try:
            sources.extend(_sources_at(path))
        except BookmarkError as exc:
            problems.append(str(exc))
    return CustomSources(tuple(sources), tuple(problems))


def chromium_sources(user_data: Path, browser: str, key_prefix: str) -> list[ProfileSource]:
    """The profiles of a Chromium `User Data` folder that hold a bookmark file."""
    names = _chromium_profile_names(user_data)
    numbered = (folder.name for folder in user_data.glob(NUMBERED_PROFILES))
    sources = []
    for folder in sorted({DEFAULT_PROFILE, *names, *numbered}):
        stores = _chromium_stores(user_data / folder)
        if stores:
            name = tidy(names.get(folder)) or folder
            sources.append(ProfileSource(f"{key_prefix}:{folder}", browser, name, stores))
    return sources


def firefox_sources(data: Path, browser: str) -> list[ProfileSource]:
    """The profiles of a Firefox data folder that have a bookmark database.

    profiles.ini names them. Its list may be incomplete, as Firefox's newer profile
    groups show, so the Profiles folder is searched as well. Folders are told apart by
    their whole path: profiles.ini may name two with the same last part.
    """
    names = _firefox_profile_names(data)
    for places in sorted((data / PROFILES_FOLDER).glob(f"*/{PLACES}")):
        folder = places.parent
        names.setdefault(folder, folder.name.partition(".")[2] or _folder_label(folder))
    return [
        _firefox_source(folder, f"firefox:{folder}", browser, name)
        for folder, name in names.items()
        if os.path.isfile(folder / PLACES)
    ]


def _user_folder(variable: str, below_home: Path) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else Path.home() / below_home


def _sources_at(path: Path) -> list[ProfileSource]:
    """Recognize what a custom path names, by the files a browser keeps there."""
    if os.path.isfile(path):
        return [_file_source(path)]
    if not os.path.isdir(path):
        raise BookmarkError(f"{path} does not exist or cannot be accessed.")
    found = _folder_sources(path)
    if not found:
        raise BookmarkError(f"{path} holds no bookmarks of Chrome, Edge, Brave or Firefox.")
    return found


def _file_source(path: Path) -> ProfileSource:
    key = f"custom:{path}"
    suffix = path.suffix.lower()
    if suffix in HTML_SUFFIXES:
        store = BookmarkStore(path, StoreFormat.HTML_EXPORT)
        return ProfileSource(key, CUSTOM_HTML, _folder_label(path), (store,))
    if suffix == SQLITE_SUFFIX:
        store = BookmarkStore(path, StoreFormat.FIREFOX_PLACES)
        return ProfileSource(key, CUSTOM_FIREFOX, _folder_label(path.parent), (store,))
    store = BookmarkStore(path, StoreFormat.CHROMIUM_JSON)
    return ProfileSource(key, CUSTOM_CHROMIUM, _folder_label(path.parent), (store,))


def _folder_sources(path: Path) -> list[ProfileSource]:
    key = f"custom:{path}"
    if os.path.isfile(path / PLACES):
        return [_firefox_source(path, key, CUSTOM_FIREFOX, _folder_label(path))]
    stores = _chromium_stores(path)
    if stores:
        return [ProfileSource(key, CUSTOM_CHROMIUM, _folder_label(path), stores)]
    if os.path.isfile(path / LOCAL_STATE):
        return chromium_sources(path, CUSTOM_CHROMIUM, key)
    if os.path.isfile(path / PROFILES_INI):
        return firefox_sources(path, CUSTOM_FIREFOX)
    return []


def _folder_label(path: Path) -> str:
    """The last part of a path; a drive root such as E:\\ has none, so it shows whole."""
    return path.name or str(path)


def _firefox_source(folder: Path, key: str, browser: str, name: str) -> ProfileSource:
    store = BookmarkStore(folder / PLACES, StoreFormat.FIREFOX_PLACES)
    return ProfileSource(key, browser, name, (store,))


def _chromium_stores(profile: Path) -> tuple[BookmarkStore, ...]:
    paths = (profile / file for file in CHROMIUM_FILES)
    return tuple(BookmarkStore(p, StoreFormat.CHROMIUM_JSON) for p in paths if os.path.isfile(p))


def _chromium_profile_names(user_data: Path) -> dict[str, str]:
    """Profile folder to the name the browser shows; empty when Local State is unusable."""
    try:
        state = json.loads((user_data / LOCAL_STATE).read_text(encoding="utf-8"))
        cache = state["profile"]["info_cache"]
        return {folder: str(info["name"]) for folder, info in cache.items() if info.get("name")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _firefox_profile_names(data: Path) -> dict[Path, str]:
    """Profile folder to its name in profiles.ini; empty when that file is unusable."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string((data / PROFILES_INI).read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, configparser.Error):
        return {}
    names: dict[Path, str] = {}
    for section in parser.sections():
        path = parser.get(section, "Path", fallback="")
        if section.startswith("Profile") and path:
            relative = parser.get(section, "IsRelative", fallback="1") != "0"
            folder = data / path if relative else Path(path)
            names[folder] = tidy(parser.get(section, "Name", fallback="")) or _folder_label(folder)
    return names
