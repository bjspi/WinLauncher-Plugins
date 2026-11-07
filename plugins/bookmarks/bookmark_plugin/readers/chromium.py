"""Read the JSON bookmark files of Chrome, Edge and other Chromium browsers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from ..domain import Bookmark, BookmarkError, inside, tidy

URL_NODE = "url"
# Chromium counts microseconds from 1601; this is how many seconds lie before 1970.
SECONDS_BEFORE_UNIX_EPOCH = 11_644_473_600
MICROSECONDS_PER_SECOND = 1_000_000


def read_chromium_bookmarks(path: Path) -> list[Bookmark]:
    """Every link of the file. The browser replaces it atomically, so it is never half-written."""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise BookmarkError(f"{path.name} could not be read: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise BookmarkError(f"{path.name} is no Chromium bookmark file.") from exc
    roots = document.get("roots") if isinstance(document, dict) else None
    if not isinstance(roots, dict):
        raise BookmarkError(f"{path.name} is no Chromium bookmark file.")
    bookmarks: list[Bookmark] = []
    for root in roots.values():
        bookmarks.extend(_links_below(root, ()))
    return bookmarks


def _links_below(node: object, folders: tuple[str, ...]) -> Iterator[Bookmark]:
    if not isinstance(node, dict):
        return
    if node.get("type") == URL_NODE:
        yield _bookmark(node, folders)
        return
    children = node.get("children")
    if isinstance(children, list):
        location = inside(folders, node.get("name"))
        for child in children:
            yield from _links_below(child, location)


def _bookmark(node: dict[str, object], folders: tuple[str, ...]) -> Bookmark:
    recency = max(_unix_seconds(node.get("date_last_used")), _unix_seconds(node.get("date_added")))
    return Bookmark(tidy(node.get("name")), tidy(node.get("url")), folders, recency)


def _unix_seconds(chromium_time: object) -> float:
    """Chromium's time, stored as text; zero or anything unusable counts as never."""
    try:
        seconds = int(str(chromium_time)) / MICROSECONDS_PER_SECOND
    except (ValueError, OverflowError):
        return 0.0
    return seconds - SECONDS_BEFORE_UNIX_EPOCH if seconds > 0 else 0.0
