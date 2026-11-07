"""Read the icons a browser cached for the sites it showed, without contacting any site."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import BookmarkError, IconFormat, IconImage, IconStore, site_of
from .snapshot import SnapshotChanging, database_copy, unreadable

PREFERRED_PIXELS = 32  # A result row's icon, sharp on a screen scaled to 200 %.
FIREFOX_VECTOR_WIDTH = 65535  # The width Firefox gives an SVG icon, which fits any size.

# Chromium: page address → icon → one bitmap per size.
CHROMIUM_PAGE_ICONS = """
    SELECT m.page_url, b.image_data, b.width
    FROM icon_mapping AS m JOIN favicon_bitmaps AS b ON b.icon_id = m.icon_id
"""
# Firefox: page address → icons, one row per size.
FIREFOX_PAGE_ICONS = """
    SELECT p.page_url, i.data, i.width
    FROM moz_pages_w_icons AS p
    JOIN moz_icons_to_pages AS t ON t.page_id = p.id
    JOIN moz_icons AS i ON i.id = t.icon_id
"""
# Firefox also keeps a site's /favicon.ico for every page of the site.
FIREFOX_SITE_ICONS = "SELECT icon_url, data, width FROM moz_icons WHERE root = 1"

IconRow = tuple[object, object, object]


@dataclass(slots=True)
class SiteIcons:
    """The best icon per page address, and per site for pages the browser holds none of."""

    pages: dict[str, IconImage] = field(default_factory=dict)
    sites: dict[str, IconImage] = field(default_factory=dict)

    def for_url(self, url: str) -> IconImage | None:
        return self.pages.get(url) or self.sites.get(site_of(url))


def read_favicons(store: IconStore, work_dir: Path, urls: Collection[str]) -> SiteIcons:
    """The icons for `urls`, kept to those, as a browser caches icons for its whole history."""
    try:
        with database_copy(store.path, work_dir) as database:
            if store.format is IconFormat.CHROMIUM_FAVICONS:
                return _best_icons(urls, database.execute(CHROMIUM_PAGE_ICONS), ())
            return _best_icons(
                urls,
                database.execute(FIREFOX_PAGE_ICONS),
                database.execute(FIREFOX_SITE_ICONS),
            )
    except (OSError, sqlite3.Error, SnapshotChanging) as exc:
        raise BookmarkError(unreadable(store.path, exc)) from exc


def _best_icons(
    urls: Collection[str], page_rows: Iterable[IconRow], site_rows: Iterable[IconRow]
) -> SiteIcons:
    wanted_pages = set(urls)
    wanted_sites = {site_of(url) for url in urls}
    icons = SiteIcons()
    for url, image in _images(page_rows):
        if url in wanted_pages:
            _keep_better(icons.pages, url, image)
        if (site := site_of(url)) in wanted_sites:
            _keep_better(icons.sites, site, image)
    for icon_url, image in _images(site_rows):
        if (site := site_of(icon_url)) in wanted_sites:
            _keep_better(icons.sites, site, image)
    return icons


def _images(rows: Iterable[IconRow]) -> Iterable[tuple[str, IconImage]]:
    """Rows with an address and image data; anything else a damaged database holds is skipped."""
    for address, data, width in rows:
        if isinstance(address, str) and isinstance(data, bytes) and data:
            yield address, IconImage(data, width if isinstance(width, int) else 0)


def _keep_better(found: dict[str, IconImage], key: str, image: IconImage) -> None:
    current = found.get(key)
    if current is None or _misfit(image) < _misfit(current):
        found[key] = image


def _misfit(image: IconImage) -> int:
    """How far an icon is from the size a row shows; a vector icon fits exactly."""
    if image.width == FIREFOX_VECTOR_WIDTH:
        return 0
    return abs(image.width - PREFERRED_PIXELS)
