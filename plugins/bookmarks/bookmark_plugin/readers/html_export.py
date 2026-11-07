"""Read the bookmarks.html every browser exports, in the old Netscape bookmark format."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from ..domain import Bookmark, BookmarkError, inside, tidy

LINK_TAG = "a"
FOLDER_TITLE_TAG = "h3"
FOLDER_LIST_TAG = "dl"
ADDRESS_ATTRIBUTE = "href"
ADDED_ATTRIBUTE = "add_date"
VISITED_ATTRIBUTE = "last_visit"


def read_html_export(path: Path) -> list[Bookmark]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise BookmarkError(f"{path.name} could not be read: {exc.strerror or exc}") from exc
    parser = _ExportParser()
    parser.feed(text)
    parser.close()
    return parser.bookmarks


class _ExportParser(HTMLParser):
    """Follow the nesting: an H3 names the DL list that comes after it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bookmarks: list[Bookmark] = []
        self._locations: list[tuple[str, ...]] = [()]
        self._next_folder = ""
        self._text: list[str] = []
        self._link: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == FOLDER_LIST_TAG:
            self._locations.append(inside(self._locations[-1], self._next_folder))
            self._next_folder = ""
        elif tag == FOLDER_TITLE_TAG:
            self._text = []
        elif tag == LINK_TAG:
            self._text = []
            self._link = dict(attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == FOLDER_LIST_TAG and len(self._locations) > 1:
            self._locations.pop()
        elif tag == FOLDER_TITLE_TAG:
            self._next_folder = "".join(self._text)
        elif tag == LINK_TAG and self._link is not None:
            self.bookmarks.append(self._bookmark(self._link))
            self._link = None

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def _bookmark(self, link: dict[str, str | None]) -> Bookmark:
        recency = max(_seconds(link.get(ADDED_ATTRIBUTE)), _seconds(link.get(VISITED_ATTRIBUTE)))
        title = tidy("".join(self._text))
        return Bookmark(title, tidy(link.get(ADDRESS_ATTRIBUTE)), self._locations[-1], recency)


def _seconds(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0
