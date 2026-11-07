"""Real host loading, each browser's storage format, source discovery and visibility."""

from __future__ import annotations

import importlib
import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from winlauncher.plugins.api import PluginContext, PluginError, SetupRequired
from winlauncher.plugins.host import MAX_ITEMS
from winlauncher.plugins.registry import discover_plugins

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
FOUND = discover_plugins([PLUGINS])
PLUGIN = next(plugin for plugin in FOUND.plugins if plugin.id == "bookmarks")
package_name = sys.modules[type(PLUGIN).__module__]._implementation.__name__
application = importlib.import_module(package_name + ".application")
discovery = importlib.import_module(package_name + ".discovery")
domain = importlib.import_module(package_name + ".domain")
chromium = importlib.import_module(package_name + ".readers.chromium")
firefox = importlib.import_module(package_name + ".readers.firefox")
favicons = importlib.import_module(package_name + ".readers.favicons")
snapshot = importlib.import_module(package_name + ".readers.snapshot")
icon_files = importlib.import_module(package_name + ".icon_files")
html_export = importlib.import_module(package_name + ".readers.html_export")
exclusions = importlib.import_module(package_name + ".exclusions")

# 2021-01-01 00:00:00 UTC in Chromium's microseconds since 1601 and in seconds since 1970.
CHROMIUM_2021 = "13253932800000000"
UNIX_2021 = 1_609_459_200.0
MICROSECONDS = 1_000_000
PNG = b"\x89PNG\r\n\x1a\n"
ICO = b"\x00\x00\x01\x00"


def write_chromium_bookmarks(path: Path, *links: tuple[str, str]) -> None:
    """A bookmark file with the links in a folder Work of the bookmark bar."""
    children = [
        {
            "type": "url",
            "name": name,
            "url": url,
            "date_added": CHROMIUM_2021,
            "date_last_used": "0",
        }
        for name, url in links
    ]
    folder = {"type": "folder", "name": "Work", "children": children}
    bar = {"type": "folder", "name": "Bookmarks bar", "children": [folder]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"roots": {"bookmark_bar": bar}}), encoding="utf-8")


def write_chromium_favicons(path: Path, *icons: tuple[str, bytes, int]) -> None:
    """A Chromium icon cache: one icon per row, linked to its page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as database, database:
        database.executescript(
            """
            CREATE TABLE icon_mapping (id INTEGER PRIMARY KEY, page_url TEXT, icon_id INTEGER);
            CREATE TABLE favicon_bitmaps (id INTEGER PRIMARY KEY, icon_id INTEGER,
                image_data BLOB, width INTEGER);
            """
        )
        for icon_id, (page, data, width) in enumerate(icons, start=1):
            database.execute("INSERT INTO icon_mapping VALUES (NULL, ?, ?)", (page, icon_id))
            database.execute(
                "INSERT INTO favicon_bitmaps VALUES (NULL, ?, ?, ?)", (icon_id, data, width)
            )


def write_places(path: Path) -> None:
    """A Firefox database in WAL mode: a bookmark, a tag entry and a bookmarklet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("PRAGMA journal_mode=WAL")
        database.executescript(
            """
            CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, last_visit_date INTEGER);
            CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER,
                parent INTEGER, title TEXT, dateAdded INTEGER, guid TEXT);
            INSERT INTO moz_places VALUES (1, 'https://www.mozilla.org/', 1700000000000000);
            INSERT INTO moz_places VALUES (2, 'javascript:alert(1)', NULL);
            INSERT INTO moz_bookmarks VALUES (1, 2, NULL, 0, '', 0, 'root________');
            INSERT INTO moz_bookmarks VALUES (2, 2, NULL, 1, 'toolbar', 0, 'toolbar_____');
            INSERT INTO moz_bookmarks VALUES (3, 2, NULL, 1, 'tags', 0, 'tags________');
            INSERT INTO moz_bookmarks VALUES (4, 2, NULL, 2, 'Tools', 0, 'folder000001');
            INSERT INTO moz_bookmarks VALUES (5, 2, NULL, 3, 'mytag', 0, 'folder000002');
            INSERT INTO moz_bookmarks VALUES (6, 1, 1, 4, 'Mozilla', 1600000000000000, 'book00000001');
            INSERT INTO moz_bookmarks VALUES (7, 1, 1, 5, NULL, 1600000000000000, 'book00000002');
            INSERT INTO moz_bookmarks VALUES (8, 1, 2, 4, 'Bookmarklet', 1, 'book00000003');
            """
        )


class BookmarksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data_dir = self.root / "plugin-data"
        self.data_dir.mkdir()

    def context(self, **options: object) -> PluginContext:
        defaults = {option.key: option.default for option in PLUGIN.options}
        return PluginContext(
            self.data_dir, {**defaults, **options}, log=logging.getLogger("bookmarks-test")
        )

    def refreshed(self, *sources: object, **options: object) -> list:
        """Refresh with the given profiles found and chosen, unless `options` say otherwise."""
        chosen = {f"profile:{source.key}": True for source in sources}
        with patch.object(application, "detected_sources", return_value=list(sources)):
            return list(PLUGIN.refresh(self.context(**{**chosen, **options})))


class HostTest(unittest.TestCase):
    def test_the_host_loads_the_plugin(self):
        self.assertEqual(FOUND.problems, [])
        self.assertEqual(PLUGIN.suggested_keywords(), ("bm", "bookmarks"))
        self.assertTrue(Path(PLUGIN.icon).is_file())


class ChromiumTest(BookmarksTestCase):
    def test_links_carry_folders_and_time(self):
        path = self.root / "Bookmarks"
        write_chromium_bookmarks(path, ("  Git\nHub ", "https://github.com/"))
        bookmark = chromium.read_chromium_bookmarks(path)[0]
        self.assertEqual(bookmark.title, "Git Hub")
        self.assertEqual(bookmark.folders, ("Bookmarks bar", "Work"))
        self.assertEqual(bookmark.recency, UNIX_2021)

    def test_an_absurd_time_counts_as_never(self):
        path = self.root / "Bookmarks"
        write_chromium_bookmarks(path, ("A", "https://a.example"))
        text = path.read_text(encoding="utf-8").replace(CHROMIUM_2021, "1" + "0" * 400)
        path.write_text(text, encoding="utf-8")
        self.assertEqual(chromium.read_chromium_bookmarks(path)[0].recency, 0.0)

    def test_a_foreign_file_is_reported(self):
        for content in ("no json", "[]", '{"roots": 1}'):
            path = self.root / "Bookmarks"
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(domain.BookmarkError):
                chromium.read_chromium_bookmarks(path)


class FirefoxTest(BookmarksTestCase):
    def test_reads_bookmarks_without_tag_entries(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        bookmarks = firefox.read_firefox_places(places, self.data_dir)
        self.assertEqual({b.title for b in bookmarks}, {"Mozilla", "Bookmarklet"})
        mozilla = next(b for b in bookmarks if b.title == "Mozilla")
        self.assertEqual(mozilla.folders, ("Bookmarks toolbar", "Tools"))
        self.assertEqual(mozilla.recency, 1_700_000_000_000_000 / MICROSECONDS)

    def test_reads_a_database_held_exclusively_including_its_log(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        with closing(sqlite3.connect(places)) as running_firefox:
            running_firefox.execute("PRAGMA locking_mode=EXCLUSIVE")
            running_firefox.execute("PRAGMA wal_autocheckpoint=0")
            with running_firefox:
                running_firefox.execute(
                    "UPDATE moz_bookmarks SET title = 'Only in the log' WHERE id = 6"
                )
            with closing(sqlite3.connect(places, timeout=0)) as other_reader:
                with self.assertRaises(sqlite3.OperationalError):
                    other_reader.execute("SELECT count(*) FROM moz_bookmarks").fetchall()
            bookmarks = firefox.read_firefox_places(places, self.data_dir)
        self.assertIn("Only in the log", {b.title for b in bookmarks})

    def test_leaves_no_copy_of_the_history_behind(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        firefox.read_firefox_places(places, self.data_dir)
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_removes_a_copy_an_interrupted_run_left_but_not_a_current_one(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        current = self.data_dir / "snapshot-current"
        current.mkdir()
        for abandoned in (self.data_dir / "snapshot-abandoned", self.data_dir / "places-legacy"):
            abandoned.mkdir()
            hours_ago = abandoned.stat().st_mtime - 2 * snapshot.ABANDONED_SNAPSHOT_SECONDS
            os.utime(abandoned, (hours_ago, hours_ago))
        firefox.read_firefox_places(places, self.data_dir)
        self.assertEqual(list(self.data_dir.iterdir()), [current])

    def test_a_retry_drops_the_log_of_the_attempt_before(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        wal = places.with_name("places.sqlite-wal")
        wal.write_bytes(b"old frames")
        # Database, log and journal: the first attempt sees a change, the second none.
        states = iter([1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 3, 3])

        def state_after_firefox_closes(path: Path) -> int:
            return next(states)

        def copy_then_close_firefox(source: Path, target: Path) -> None:
            Path(target).write_bytes(Path(source).read_bytes())
            if Path(source) == wal:
                wal.unlink()

        folder = self.root / "copy"
        folder.mkdir()
        with (
            patch.object(snapshot, "_state", state_after_firefox_closes),
            patch.object(snapshot.shutil, "copyfile", copy_then_close_firefox),
            patch.object(snapshot.time, "sleep"),
        ):
            copy = snapshot._snapshot(places, folder)
        self.assertFalse(copy.with_name(wal.name).exists())

    def test_a_database_that_keeps_changing_is_reported_after_waiting(self):
        places = self.root / "profile" / "places.sqlite"
        write_places(places)
        states = iter(range(100))
        with (
            patch.object(snapshot, "_state", lambda path: next(states)),
            patch.object(snapshot.time, "sleep") as sleep,
            self.assertRaises(domain.BookmarkError),
        ):
            firefox.read_firefox_places(places, self.data_dir)
        self.assertEqual(sleep.call_count, snapshot.SNAPSHOT_ATTEMPTS - 1)

    def test_a_damaged_database_is_reported(self):
        places = self.root / "places.sqlite"
        places.write_bytes(b"not a database" * 100)
        with self.assertRaises(domain.BookmarkError):
            firefox.read_firefox_places(places, self.data_dir)


class HtmlExportTest(BookmarksTestCase):
    def test_follows_the_nesting_of_folders(self):
        path = self.root / "bookmarks.html"
        path.write_text(
            """<!DOCTYPE NETSCAPE-Bookmark-file-1>
            <H1>Bookmarks</H1>
            <DL><p>
              <DT><H3 ADD_DATE="1">Work &amp; Life</H3>
              <DL><p>
                <DT><A HREF="https://a.example/" ADD_DATE="1600000000">A &amp; B</A>
                <DT><H3>Inner</H3>
                <DL><p><DT><A HREF="https://b.example/">Deep</A></DL><p>
                <DT><A HREF="https://c.example/">After inner</A>
              </DL><p>
              <DT><A HREF="https://d.example/">Top</A>
            </DL>""",
            encoding="utf-8",
        )
        found = {b.title: b for b in html_export.read_html_export(path)}
        self.assertEqual(found["A & B"].folders, ("Work & Life",))
        self.assertEqual(found["A & B"].recency, 1_600_000_000.0)
        self.assertEqual(found["Deep"].folders, ("Work & Life", "Inner"))
        self.assertEqual(found["After inner"].folders, ("Work & Life",))
        self.assertEqual(found["Top"].folders, ())


class DiscoveryTest(BookmarksTestCase):
    def test_chromium_profiles_are_named_and_need_a_bookmark_file(self):
        data = self.root / "User Data"
        write_chromium_bookmarks(data / "Default" / "AccountBookmarks", ("A", "https://a.example"))
        write_chromium_bookmarks(data / "Profile 3" / "Bookmarks", ("B", "https://b.example"))
        (data / "Profile 4").mkdir()
        (data / "System Profile").mkdir()
        state = {"profile": {"info_cache": {"Default": {"name": "Personal"}}}}
        (data / "Local State").write_text(json.dumps(state), encoding="utf-8")
        sources = discovery.chromium_sources(data, "Chrome", "chrome")
        self.assertEqual(
            [(s.key, s.profile) for s in sources],
            [("chrome:Default", "Personal"), ("chrome:Profile 3", "Profile 3")],
        )

    def test_damaged_local_state_keeps_the_profiles(self):
        data = self.root / "User Data"
        write_chromium_bookmarks(data / "Default" / "Bookmarks", ("A", "https://a.example"))
        for content in ("no json", "[]", '{"profile": {"info_cache": {"Default": 1}}}'):
            (data / "Local State").write_text(content, encoding="utf-8")
            with self.subTest(content=content):
                sources = discovery.chromium_sources(data, "Chrome", "chrome")
                self.assertEqual([s.profile for s in sources], ["Default"])

    def test_firefox_profiles_come_from_the_ini_and_the_folder(self):
        data = self.root / "Firefox"
        write_places(data / "Profiles" / "abc.listed" / "places.sqlite")
        write_places(data / "Profiles" / "def.unlisted" / "places.sqlite")
        elsewhere = self.root / "elsewhere"
        write_places(elsewhere / "places.sqlite")
        (data / "profiles.ini").write_text(
            f"""[General]
Version=2
[Profile0]
Name=Mine
IsRelative=1
Path=Profiles/abc.listed
[Profile1]
Name=Moved
IsRelative=0
Path={elsewhere}
[Profile2]
Name=Without database
IsRelative=1
Path=Profiles/none
[InstallABC]
Default=Profiles/abc.listed
""",
            encoding="utf-8",
        )
        names = {s.profile for s in discovery.firefox_sources(data, "Firefox")}
        self.assertEqual(names, {"Mine", "Moved", "unlisted"})

    def test_custom_paths_are_recognized_by_what_they_hold(self):
        profile = self.root / "portable" / "profile"
        write_places(profile / "places.sqlite")
        chrome_profile = self.root / "chrome-profile"
        write_chromium_bookmarks(chrome_profile / "Bookmarks", ("A", "https://a.example"))
        user_data = self.root / "User Data"
        write_chromium_bookmarks(user_data / "Default" / "Bookmarks", ("A", "https://a.example"))
        (user_data / "Local State").write_text("{}", encoding="utf-8")
        exported = self.root / "export.HTML"
        exported.write_text("<DL></DL>", encoding="utf-8")
        cases = {
            str(profile): domain.StoreFormat.FIREFOX_PLACES,
            str(profile / "places.sqlite"): domain.StoreFormat.FIREFOX_PLACES,
            str(chrome_profile): domain.StoreFormat.CHROMIUM_JSON,
            str(chrome_profile / "Bookmarks"): domain.StoreFormat.CHROMIUM_JSON,
            str(user_data): domain.StoreFormat.CHROMIUM_JSON,
            f'"{exported}"': domain.StoreFormat.HTML_EXPORT,
        }
        for line, store_format in cases.items():
            with self.subTest(line=line):
                custom = discovery.custom_sources(f"\n  {line}  \n")
                self.assertEqual(custom.problems, ())
                self.assertEqual(custom.sources[0].stores[0].format, store_format)

    def test_two_firefox_profiles_with_one_folder_name_stay_apart(self):
        data = self.root / "Firefox"
        first, second = self.root / "a" / "default", self.root / "b" / "default"
        write_places(first / "places.sqlite")
        write_places(second / "places.sqlite")
        data.mkdir()
        (data / "profiles.ini").write_text(
            f"[Profile0]\nIsRelative=0\nPath={first}\n[Profile1]\nIsRelative=0\nPath={second}\n",
            encoding="utf-8",
        )
        keys = [source.key for source in discovery.firefox_sources(data, "Firefox")]
        self.assertEqual(len(set(keys)), 2)

    def test_every_profile_has_a_name_to_show(self):
        data = self.root / "Firefox"
        write_places(data / "Profiles" / "abc.main" / "places.sqlite")
        (data / "profiles.ini").write_text(
            "[Profile0]\nName=\nIsRelative=1\nPath=Profiles/abc.main\n", encoding="utf-8"
        )
        self.assertEqual(discovery.firefox_sources(data, "Firefox")[0].profile, "abc.main")
        chrome = self.root / "User Data"
        write_chromium_bookmarks(chrome / "Default" / "Bookmarks", ("A", "https://a.example"))
        state = {"profile": {"info_cache": {"Default": {"name": "  "}}}}
        (chrome / "Local State").write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(discovery.chromium_sources(chrome, "Chrome", "c")[0].profile, "Default")

    def test_a_drive_root_shows_whole_as_the_profile(self):
        self.assertEqual(discovery._folder_label(Path("E:/")), str(Path("E:/")))

    def test_an_inaccessible_custom_path_is_a_problem(self):
        with patch.object(Path, "stat", side_effect=PermissionError(13, "Access is denied")):
            custom = discovery.custom_sources(str(self.root / "Bookmarks"))
        self.assertEqual(custom.sources, ())
        self.assertIn("cannot be accessed", custom.problems[0])

    def test_a_custom_path_without_bookmarks_is_a_problem(self):
        custom = discovery.custom_sources(f"{self.root}\n{self.root / 'missing'}")
        self.assertEqual(custom.sources, ())
        self.assertEqual(len(custom.problems), 2)


class DetectedBrowsersTest(BookmarksTestCase):
    def test_every_browser_is_found_in_its_standard_folder(self):
        local, roaming = self.root / "Local", self.root / "Roaming"
        for folder in (discovery.CHROME_DATA, discovery.EDGE_DATA, discovery.BRAVE_DATA):
            write_chromium_bookmarks(local / folder / "Default" / "Bookmarks", ("A", "https://a.b"))
        write_places(roaming / discovery.FIREFOX_DATA / "Profiles" / "x.main" / "places.sqlite")
        environment = {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}
        with patch.dict(discovery.os.environ, environment):
            found = {source.key: source.browser for source in discovery.detected_sources()}
        self.assertEqual(
            found,
            {
                "chrome:Default": "Chrome",
                "edge:Default": "Edge",
                "brave:Default": "Brave",
                f"firefox:{roaming / discovery.FIREFOX_DATA / 'Profiles' / 'x.main'}": "Firefox",
            },
        )


class FaviconsTest(BookmarksTestCase):
    def test_chromium_picks_the_row_size_and_falls_back_to_the_site(self):
        path = self.root / "Favicons"
        write_chromium_favicons(
            path,
            ("https://a.example/page", PNG + b"16", 16),
            ("https://a.example/page", PNG + b"32", 32),
            ("https://a.example/other", PNG + b"other", 32),
            ("https://unwanted.example/", PNG + b"unwanted", 32),
        )
        store = domain.IconStore(path, domain.IconFormat.CHROMIUM_FAVICONS)
        wanted = {"https://a.example/page", "https://www.a.example/never-shown"}
        icons = favicons.read_favicons(store, self.data_dir, wanted)
        self.assertEqual(icons.for_url("https://a.example/page").data, PNG + b"32")
        self.assertIsNotNone(icons.for_url("https://www.a.example/never-shown"))
        self.assertNotIn("https://unwanted.example/", icons.pages)
        self.assertNotIn("unwanted.example", icons.sites)
        self.assertEqual(list(self.data_dir.iterdir()), [])  # The copy is gone.

    def test_firefox_prefers_vector_icons_and_knows_site_icons(self):
        path = self.root / "favicons.sqlite"
        with closing(sqlite3.connect(path)) as database, database:
            database.executescript(
                """
                CREATE TABLE moz_icons (id INTEGER PRIMARY KEY, icon_url TEXT, data BLOB,
                    width INTEGER, root INTEGER);
                CREATE TABLE moz_pages_w_icons (id INTEGER PRIMARY KEY, page_url TEXT);
                CREATE TABLE moz_icons_to_pages (page_id INTEGER, icon_id INTEGER);
                INSERT INTO moz_pages_w_icons VALUES (1, 'https://a.example/');
                INSERT INTO moz_icons_to_pages VALUES (1, 1), (1, 2);
                """
            )
            database.executemany(
                "INSERT INTO moz_icons VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "https://a.example/icon.png", PNG, 16, 0),
                    (2, "https://a.example/icon.svg", b"<svg/>", 65535, 0),
                    (3, "https://b.example/favicon.ico", ICO, 16, 1),
                ],
            )
        store = domain.IconStore(path, domain.IconFormat.FIREFOX_FAVICONS)
        wanted = {"https://a.example/", "https://b.example/x"}
        icons = favicons.read_favicons(store, self.data_dir, wanted)
        self.assertEqual(icons.for_url("https://a.example/").data, b"<svg/>")
        self.assertEqual(icons.for_url("https://b.example/x").data, ICO)

    def test_a_damaged_cache_is_reported(self):
        path = self.root / "Favicons"
        path.write_bytes(b"not a database" * 100)
        store = domain.IconStore(path, domain.IconFormat.CHROMIUM_FAVICONS)
        with self.assertRaises(domain.BookmarkError):
            favicons.read_favicons(store, self.data_dir, {"https://a.example/"})

    def test_profiles_name_their_icon_cache(self):
        data = self.root / "User Data"
        write_chromium_bookmarks(data / "Default" / "Bookmarks", ("A", "https://a.example"))
        write_chromium_favicons(data / "Default" / "Favicons")
        source = discovery.chromium_sources(data, "Chrome", "chrome")[0]
        self.assertEqual(source.icons.format, domain.IconFormat.CHROMIUM_FAVICONS)
        write_places(self.root / "ff" / "places.sqlite")
        (self.root / "ff" / "favicons.sqlite").write_bytes(b"")
        custom = discovery.custom_sources(str(self.root / "ff")).sources[0]
        self.assertEqual(custom.icons.format, domain.IconFormat.FIREFOX_FAVICONS)


class IconFilesTest(BookmarksTestCase):
    def test_recognizes_the_formats_winlauncher_draws(self):
        cases = {
            PNG: ".png",
            ICO: ".ico",
            b"GIF89a...": ".gif",
            b"\xff\xd8\xff\xe0": ".jpg",
            b"RIFF\x00\x00\x00\x00WEBPVP8 ": ".webp",
            b"\xef\xbb\xbf  <svg xmlns='x'/>": ".svg",
            b'<?xml version="1.0"?>\n<SVG/>': ".svg",
            b"<html>": None,
            b"BM": None,
        }
        for data, suffix in cases.items():
            with self.subTest(data=data):
                self.assertEqual(icon_files.image_suffix(data), suffix)

    def test_equal_icons_share_a_file_and_unused_ones_are_removed(self):
        files = icon_files.IconFiles(self.data_dir)
        first = files.path_for(domain.IconImage(PNG + b"a", 16))
        self.assertEqual(files.path_for(domain.IconImage(PNG + b"a", 32)), first)
        self.assertEqual(files.path_for(domain.IconImage(b"<html>", 16)), "")
        self.assertEqual(files.path_for(None), "")
        stale = Path(first).with_name("stale.png")
        stale.write_bytes(PNG)
        files.remove_unused()
        self.assertEqual(list(Path(first).parent.iterdir()), [Path(first)])


class AddressTest(unittest.TestCase):
    def test_the_short_address_shows_the_site_and_the_first_part_of_the_path(self):
        cases = {
            "https://www.github.com/bjspi/WinLauncher/issues": "github.com/bjspi/…",
            "https://github.com/bjspi": "github.com/bjspi",
            "https://github.com/bjspi/": "github.com/bjspi",
            "https://example.com/?q=1": "example.com",
            "https://example.com": "example.com",
            "http://[": "",
        }
        for url, shown in cases.items():
            with self.subTest(url=url):
                self.assertEqual(domain.Bookmark("", url).short_address, shown)


class VisibilityTest(unittest.TestCase):
    def test_exclusions_match_title_address_and_folders_ignoring_case(self):
        bookmark = domain.Bookmark("Bank Login", "https://bank.example/in", ("Private", "Money"))
        patterns = ("bank login", "*LOGIN", "*ank*", "[bc]ank?login", "https://bank.*", "private")
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertTrue(domain.is_excluded(bookmark, domain.parse_patterns(pattern)))
        self.assertFalse(domain.is_excluded(bookmark, domain.parse_patterns("bank\n\nwork")))

    def test_only_openable_addresses_are_listed(self):
        for url in (
            "file:///C:/run.bat",
            "file://attacker.example/share/x.exe",
            "javascript:alert(1)",
            "place:sort=8",
            "chrome://settings",
            "ms-msdt:x",
            "http://[",
        ):
            with self.subTest(url=url):
                self.assertFalse(domain.is_openable(url))
        for url in ("https://a.example", "HTTP://a.example", "ftp://a.example"):
            with self.subTest(url=url):
                self.assertTrue(domain.is_openable(url))

    def test_recent_first_one_row_per_address_up_to_the_limit(self):
        found = [
            domain.Bookmark("Old", "https://a.example", recency=1, browser="Edge"),
            domain.Bookmark("New", "https://a.example", recency=3, browser="Chrome"),
            domain.Bookmark("Middle", "https://b.example", recency=2),
            domain.Bookmark("Oldest", "https://c.example", recency=0),
        ]
        shown = domain.visible_bookmarks(found, (), 2)
        self.assertEqual([b.title for b in shown], ["New", "Middle"])
        self.assertEqual(shown[0].browser, "Chrome")


class RefreshTest(BookmarksTestCase):
    def source(self, key: str = "chrome:Default", url: str = "https://www.a.example/x"):
        path = self.root / key.replace(":", "-") / "Bookmarks"
        write_chromium_bookmarks(path, ("", url))
        store = domain.BookmarkStore(path, domain.StoreFormat.CHROMIUM_JSON)
        return domain.ProfileSource(key, "Chrome", "Personal", (store,))

    def test_items_show_where_a_bookmark_lies_and_find_it_by_site(self):
        item = self.refreshed(self.source())[0]
        self.assertEqual(item.key, "https://www.a.example/x")
        self.assertEqual(item.target, "https://www.a.example/x")
        self.assertEqual(item.name, "https://www.a.example/x")  # It has no title.
        self.assertEqual(item.keywords, ("a.example", "Bookmarks bar", "Work"))
        self.assertEqual(item.breadcrumbs, ("Chrome", "Personal", "Bookmarks bar", "Work"))
        self.assertEqual([chip.text for chip in item.chips], ["a.example/x"])
        self.assertEqual(item.icon, "")  # The profile has no icon cache.

    def with_icons(self, source, icons: Path):
        store = domain.IconStore(icons, domain.IconFormat.CHROMIUM_FAVICONS)
        return domain.ProfileSource(
            source.key, source.browser, source.profile, source.stores, store
        )

    def test_items_show_the_icon_the_browser_cached(self):
        source = self.source()
        icons = source.stores[0].path.with_name("Favicons")
        write_chromium_favicons(icons, ("https://www.a.example/x", PNG + b"page", 16))
        item = self.refreshed(self.with_icons(source, icons))[0]
        self.assertEqual(Path(item.icon).read_bytes(), PNG + b"page")
        self.assertEqual(Path(item.icon).parent, self.data_dir / icon_files.ICONS_FOLDER)

    def test_an_unreadable_icon_cache_still_lists_the_bookmarks(self):
        source = self.source()
        icons = source.stores[0].path.with_name("Favicons")
        icons.write_bytes(b"not a database" * 100)
        items = self.refreshed(self.with_icons(source, icons))
        self.assertEqual([item.icon for item in items], [""])

    def test_a_profile_is_read_only_once_chosen(self):
        source = self.source()
        with self.assertRaises(SetupRequired):
            self.refreshed(source, **{f"profile:{source.key}": False})
        with patch.object(application, "detected_sources", return_value=[source]):
            with self.assertRaises(SetupRequired):  # Found after loading: it has no switch yet.
                PLUGIN.refresh(self.context())
        self.assertEqual(len(self.refreshed(source)), 1)

    def test_a_custom_path_needs_no_choosing(self):
        source = self.source()
        items = self.refreshed(custom_paths=str(source.stores[0].path))
        self.assertEqual(len(items), 1)

    def test_excluded_bookmarks_are_not_listed(self):
        self.assertEqual(self.refreshed(self.source(), excluded="work"), [])

    def choose_with(self, ticked: set[str] | None):
        """A context whose checklist ticks `ticked`, recording the rows it showed."""
        shown = []

        def choose(title, text, choices):
            shown.extend(choices)
            return None if ticked is None else frozenset(ticked)

        return replace(self.context(), choose=choose), shown

    def test_exclude_offers_the_bookmark_and_its_folders(self):
        source = self.source()
        (item,) = self.refreshed(source)
        context, shown = self.choose_with(None)
        self.assertFalse(PLUGIN.exclude(item, context))
        self.assertEqual(
            [(row.key, row.detail, row.checked) for row in shown],
            [
                ("bookmark", item.name, True),
                ("folder:4", "Chrome › Personal › Bookmarks bar › Work", False),
                ("folder:3", "Chrome › Personal › Bookmarks bar", False),
            ],
        )
        self.assertEqual(exclusions.read_exclusions(self.data_dir), domain.Exclusions())

    def test_an_excluded_folder_hides_what_lies_below_it_until_restored(self):
        source = self.source()
        (item,) = self.refreshed(source)
        context, _shown = self.choose_with({"folder:3"})
        self.assertTrue(PLUGIN.exclude(item, context))
        self.assertEqual(self.refreshed(source), [])
        context, shown = self.choose_with(set())
        self.assertIn("1 restored", application.restore_bookmarks(context))
        self.assertEqual([row.detail for row in shown], ["Chrome › Personal › Bookmarks bar"])
        self.assertEqual(len(self.refreshed(source)), 1)

    def test_an_excluded_bookmark_is_hidden_in_every_browser(self):
        (item,) = self.refreshed(self.source())
        context, _shown = self.choose_with({"bookmark"})
        self.assertTrue(PLUGIN.exclude(item, context))
        self.assertEqual(self.refreshed(self.source("edge:Default")), [])
        saved = exclusions.read_exclusions(self.data_dir)
        self.assertEqual(dict(saved.addresses), {item.key: item.name})

    def test_a_folder_of_the_same_name_elsewhere_stays_listed(self):
        excluded = domain.Exclusions(folders=(("Chrome", "Personal", "Work"),))
        here = domain.Bookmark("A", "https://a.example", ("Work", "Old"), 0, "Chrome", "Personal")
        elsewhere = domain.Bookmark(
            "B", "https://b.example", ("Bar", "Work"), 0, "Chrome", "Personal"
        )
        other = domain.Bookmark("C", "https://c.example", ("Work",), 0, "Edge", "Personal")
        self.assertEqual(
            [excluded.hides(b) for b in (here, elsewhere, other)],
            [True, False, False],
        )

    def test_a_damaged_exclusion_file_fails_the_refresh(self):
        (self.data_dir / exclusions.EXCLUSIONS_FILE).write_text('{"addresses": 1}', "utf-8")
        with self.assertRaisesRegex(PluginError, "damaged"):
            self.refreshed(self.source())

    def test_restoring_nothing_says_how_to_exclude(self):
        context, _shown = self.choose_with(None)
        self.assertIn("Right-click", application.restore_bookmarks(context))

    def test_one_broken_path_does_not_hide_the_others(self):
        items = self.refreshed(self.source(), custom_paths=str(self.root / "missing"))
        self.assertEqual(len(items), 1)

    def test_nothing_readable_is_an_error(self):
        with self.assertRaises(PluginError) as caught:
            self.refreshed(custom_paths=str(self.root / "missing"))
        self.assertIn("missing", str(caught.exception))

    def test_no_chosen_profile_clears_the_list_despite_a_broken_path(self):
        source = self.source()
        with self.assertRaises(SetupRequired) as caught:
            self.refreshed(
                source,
                **{f"profile:{source.key}": False, "custom_paths": str(self.root / "missing")},
            )
        self.assertIn("missing", str(caught.exception))

    def test_an_empty_profile_and_a_broken_path_are_no_failure(self):
        empty = self.root / "empty" / "Bookmarks"
        empty.parent.mkdir()
        empty.write_text('{"roots": {}}', encoding="utf-8")
        store = domain.BookmarkStore(empty, domain.StoreFormat.CHROMIUM_JSON)
        source = domain.ProfileSource("chrome:Default", "Chrome", "Personal", (store,))
        self.assertEqual(self.refreshed(source, custom_paths=str(self.root / "missing")), [])

    def test_only_unreadable_stores_are_an_error(self):
        damaged = self.root / "Bookmarks"
        damaged.write_text("no json", encoding="utf-8")
        with self.assertRaises(PluginError) as caught:
            self.refreshed(custom_paths=str(damaged))
        self.assertNotIsInstance(caught.exception, SetupRequired)

    def test_a_store_failing_unforeseen_does_not_hide_the_others(self):
        source, broken = self.source(), self.source("edge:Default", "https://b.example")
        real_reader = chromium.read_chromium_bookmarks
        catalog = importlib.import_module(package_name + ".catalog")

        def fail_for_edge(path: Path) -> list:
            if "edge" in str(path):
                raise RecursionError("too deep")
            return real_reader(path)

        with patch.object(catalog, "read_chromium_bookmarks", fail_for_edge):
            items = self.refreshed(source, broken)
        self.assertEqual([item.target for item in items], ["https://www.a.example/x"])

    def test_the_limit_stays_within_what_the_host_keeps(self):
        limit = next(option for option in PLUGIN.options if option.key == "limit")
        self.assertEqual(limit.bounds[1], MAX_ITEMS)

    def test_a_cancelled_refresh_returns(self):
        source = self.source()
        context = self.context(**{f"profile:{source.key}": True})
        context.cancel.set()
        with patch.object(application, "detected_sources", return_value=[source]):
            self.assertEqual(list(PLUGIN.refresh(context)), [])

    def test_show_sources_names_counts_and_profiles_not_chosen(self):
        on, off = self.source(), self.source("edge:Default")
        options = {f"profile:{on.key}": True, "custom_paths": str(self.root / "missing")}
        with patch.object(application, "detected_sources", return_value=[on, off]):
            message = application.show_sources(self.context(**options))
        self.assertIn(f"{on.description}: 1 bookmarks", message)
        self.assertIn(f"{off.description}: not chosen", message)
        self.assertIn("does not exist", message)


class ReadSourcesTest(BookmarksTestCase):
    def test_a_cancelled_run_stops_before_the_next_source(self):
        cancel = threading.Event()
        cancel.set()
        source = domain.ProfileSource("k", "Chrome", "P", ())
        catalog = importlib.import_module(package_name + ".catalog")
        self.assertEqual(catalog.read_sources([source], self.data_dir, cancel), [])


if __name__ == "__main__":
    unittest.main()
