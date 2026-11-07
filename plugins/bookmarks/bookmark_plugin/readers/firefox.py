"""Read Firefox's places.sqlite through a private copy, never the database itself.

A current Firefox lets others read the database while it runs, but SQLite answers
"database is locked" whenever a process holds it in exclusive mode. Opening it would
also make this plugin take part in the locking of a database that holds the user's
browsing history, every few minutes, and could leave SQLite's side files in the
profile. Copying only reads the files, so it depends on none of this and leaves the
browser alone. Recent changes may still be in the write-ahead log, which is why that
is copied as well.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ..domain import Bookmark, BookmarkError, inside, tidy

WAL_SUFFIX = "-wal"
SNAPSHOT_PREFIX = "places-"
SNAPSHOT_ATTEMPTS = 3  # Firefox rarely writes; a copy that overlapped a write is retried.
SNAPSHOT_RETRY_SECONDS = 1.0  # Gives a burst of writes the time to end.
# A copy this old belongs to no running refresh: a crash or power loss left it behind.
ABANDONED_SNAPSHOT_SECONDS = 60 * 60
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
        _remove_abandoned_snapshots(work_dir)
        with tempfile.TemporaryDirectory(prefix=SNAPSHOT_PREFIX, dir=work_dir) as folder:
            copy = _snapshot(places, Path(folder))
            with closing(sqlite3.connect(copy)) as database:
                return _bookmarks_in(database)
    except OSError as exc:
        raise BookmarkError(f"{places.name} could not be read: {exc.strerror or exc}") from exc
    except sqlite3.Error as exc:
        raise BookmarkError(f"{places.name} could not be read: {exc}") from exc


def _remove_abandoned_snapshots(work_dir: Path) -> None:
    """Delete copies of the history an interrupted run left; a current one stays."""
    oldest_current = time.time() - ABANDONED_SNAPSHOT_SECONDS
    for folder in work_dir.glob(f"{SNAPSHOT_PREFIX}*"):
        if folder.stat().st_mtime < oldest_current:
            shutil.rmtree(folder, ignore_errors=True)


def _snapshot(places: Path, folder: Path) -> Path:
    """Copy the database and its log, again if Firefox wrote to them meanwhile.

    A log copied by an earlier attempt goes first: replayed over a newer database,
    it would bring back old rows or damage the copy.
    """
    wal = places.with_name(places.name + WAL_SUFFIX)
    copy = folder / places.name
    copied_wal = copy.with_name(wal.name)
    for attempt in range(SNAPSHOT_ATTEMPTS):
        if attempt:
            time.sleep(SNAPSHOT_RETRY_SECONDS)
        before = _state(places), _state(wal)
        copied_wal.unlink(missing_ok=True)
        shutil.copyfile(places, copy)
        if wal.exists():
            shutil.copyfile(wal, copied_wal)
        if before == (_state(places), _state(wal)):
            return copy
    raise BookmarkError(f"{places.name} kept changing while it was copied.")


def _state(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except FileNotFoundError:
        return None
    return status.st_mtime_ns, status.st_size


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
