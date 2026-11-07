"""Read the bookmarks of Firefox's places.sqlite, through a private copy of it."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..domain import Bookmark, BookmarkError, inside, tidy
from .snapshot import SnapshotChanging, database_copy, unreadable

MICROSECONDS_PER_SECOND = 1_000_000

ROOT_GUID = "root________"
TAGS_GUID = "tags________"
# Firefox's root folders carry internal titles such as "toolbar".
ROOT_FOLDER_NAMES = {
    "menu________": "Bookmarks menu",
    "toolbar_____": "Bookmarks toolbar",
    "unfiled_____": "Other bookmarks",
    "mobile______": "Mobile bookmarks",
}

BOOKMARK_TYPE = 1
FOLDER_TYPE = 2
FOLDERS_QUERY = "SELECT id, parent, title, guid FROM moz_bookmarks WHERE type = ?"
LINKS_QUERY = """
    SELECT b.title, p.url, b.parent, b.dateAdded, p.last_visit_date
    FROM moz_bookmarks AS b JOIN moz_places AS p ON p.id = b.fk
    WHERE b.type = ?
"""


@dataclass(frozen=True, slots=True)
class _Folder:
    parent: int
    title: str | None
    guid: str


def read_firefox_places(places: Path, work_dir: Path) -> list[Bookmark]:
    """Every bookmark of the database; the copy with its browsing history is deleted again."""
    try:
        with database_copy(places, work_dir) as database:
            return _bookmarks_in(database)
    except (OSError, sqlite3.Error, SnapshotChanging) as exc:
        raise BookmarkError(unreadable(places, exc)) from exc


def _bookmarks_in(database: sqlite3.Connection) -> list[Bookmark]:
    folders = {
        row_id: _Folder(parent, title, guid)
        for row_id, parent, title, guid in database.execute(FOLDERS_QUERY, (FOLDER_TYPE,))
    }
    bookmarks = []
    for title, url, parent, added, visited in database.execute(LINKS_QUERY, (BOOKMARK_TYPE,)):
        location = _location(parent, folders)
        if location is not None:
            recency = max(added or 0, visited or 0) / MICROSECONDS_PER_SECOND
            bookmarks.append(Bookmark(tidy(title), tidy(url), location, recency))
    return bookmarks


def _location(folder_id: int, folders: dict[int, _Folder]) -> tuple[str, ...] | None:
    """The folder names from the outermost in; None below Tags, which holds no bookmarks.

    Firefox represents a tag as a folder of further entries for the same address.
    """
    path: list[str] = []
    seen: set[int] = set()
    while (folder := folders.get(folder_id)) is not None and folder_id not in seen:
        seen.add(folder_id)
        if folder.guid == TAGS_GUID:
            return None
        if folder.guid != ROOT_GUID:
            path.append(ROOT_FOLDER_NAMES.get(folder.guid) or tidy(folder.title))
        folder_id = folder.parent
    location: tuple[str, ...] = ()
    for name in reversed(path):
        location = inside(location, name)
    return location
