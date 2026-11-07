"""Read a browser's SQLite database through a private copy, never the database itself.

Browsers may hold their databases in exclusive mode, and SQLite then answers
"database is locked". Opening one would also make this plugin take part in the
locking of files that hold the user's browsing history, every few minutes, and could
leave SQLite's side files in the profile. Copying only reads the files, so it depends
on none of this and leaves the browser alone. Recent changes may still be in the
write-ahead log or the rollback journal, which is why those are copied as well.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

SIDE_FILE_SUFFIXES = ("-wal", "-journal")
SNAPSHOT_PREFIX = "snapshot-"
# Version 1.0.0 named its copies so; they are cleaned up like the current ones.
LEGACY_SNAPSHOT_PREFIX = "places-"
SNAPSHOT_ATTEMPTS = 3  # Browsers rarely write; a copy that overlapped a write is retried.
SNAPSHOT_RETRY_SECONDS = 1.0  # Gives a burst of writes the time to end.
# A copy this old belongs to no running refresh: a crash or power loss left it behind.
ABANDONED_SNAPSHOT_SECONDS = 60 * 60


class SnapshotChanging(Exception):
    """The database changed during every attempt to copy it."""


@contextmanager
def database_copy(database: Path, work_dir: Path) -> Iterator[sqlite3.Connection]:
    """A connection to a copy of `database`; the copy is deleted again afterwards.

    Raises OSError, sqlite3.Error or SnapshotChanging; the caller says what it read.
    """
    _remove_abandoned_snapshots(work_dir)
    with tempfile.TemporaryDirectory(prefix=SNAPSHOT_PREFIX, dir=work_dir) as folder:
        copy = _snapshot(database, Path(folder))
        with closing(sqlite3.connect(copy)) as connection:
            yield connection


def unreadable(database: Path, exc: Exception) -> str:
    """The message for a database that could not be read."""
    if isinstance(exc, SnapshotChanging):
        return f"{database.name} kept changing while it was copied."
    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
    return f"{database.name} could not be read: {reason}"


def _remove_abandoned_snapshots(work_dir: Path) -> None:
    """Delete copies of the history an interrupted run left; a current one stays."""
    oldest_current = time.time() - ABANDONED_SNAPSHOT_SECONDS
    for prefix in (SNAPSHOT_PREFIX, LEGACY_SNAPSHOT_PREFIX):
        for folder in work_dir.glob(f"{prefix}*"):
            if folder.stat().st_mtime < oldest_current:
                shutil.rmtree(folder, ignore_errors=True)


def _snapshot(database: Path, folder: Path) -> Path:
    """Copy the database and its side files, again if the browser wrote to them meanwhile.

    Side files copied by an earlier attempt go first: replayed over a newer database,
    an old log would bring back old rows or damage the copy.
    """
    sides = [database.with_name(database.name + suffix) for suffix in SIDE_FILE_SUFFIXES]
    copy = folder / database.name
    for attempt in range(SNAPSHOT_ATTEMPTS):
        if attempt:
            time.sleep(SNAPSHOT_RETRY_SECONDS)
        before = [_state(path) for path in (database, *sides)]
        for side in sides:
            copy.with_name(side.name).unlink(missing_ok=True)
        shutil.copyfile(database, copy)
        for side in sides:
            if side.exists():
                shutil.copyfile(side, copy.with_name(side.name))
        if before == [_state(path) for path in (database, *sides)]:
            return copy
    raise SnapshotChanging(database)


def _state(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except FileNotFoundError:
        return None
    return status.st_mtime_ns, status.st_size
