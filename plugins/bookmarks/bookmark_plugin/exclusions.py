"""Bookmarks and folders the user excluded, kept in the plugin's data folder.

Exclude… on a result adds to them, Excluded bookmarks… on the settings card takes
them back. A damaged file fails the refresh instead of showing everything again.
"""

from __future__ import annotations

import json
from pathlib import Path

from .domain import BookmarkError, Exclusions

EXCLUSIONS_FILE = "excluded-bookmarks.json"
ADDRESSES = "addresses"  # Address to the title it had, for showing it again.
FOLDERS = "folders"  # Locations as lists: browser, profile, then folders outermost first.


def read_exclusions(folder: Path) -> Exclusions:
    try:
        saved = json.loads((folder / EXCLUSIONS_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Exclusions()
    except (OSError, ValueError) as exc:
        raise BookmarkError(f"Could not read the excluded bookmarks: {exc}") from exc
    try:
        addresses = saved[ADDRESSES]
        folders = tuple(tuple(location) for location in saved[FOLDERS])
    except (KeyError, TypeError) as exc:
        raise BookmarkError(f"{EXCLUSIONS_FILE} is damaged: {exc!r}") from exc
    if not _is_text_map(addresses) or not all(_is_text_tuple(f) for f in folders):
        raise BookmarkError(f"{EXCLUSIONS_FILE} is damaged: it holds more than text.")
    return Exclusions(addresses, folders)


def write_exclusions(folder: Path, exclusions: Exclusions) -> None:
    """Replace atomically, so an interrupted write cannot lose what was excluded."""
    saved = {
        ADDRESSES: dict(exclusions.addresses),
        FOLDERS: [list(location) for location in exclusions.folders],
    }
    path = folder / EXCLUSIONS_FILE
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise BookmarkError(f"Could not save the excluded bookmarks: {exc}") from exc


def _is_text_map(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(title, str) for key, title in value.items()
    )


def _is_text_tuple(value: tuple) -> bool:
    return bool(value) and all(isinstance(part, str) for part in value)
