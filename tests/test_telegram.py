"""Links, items and dialog conversion; no test contacts Telegram.

The plugin is a folder, not an installed package, so the module is loaded the way
WinLauncher loads it: `discover_plugins` for the folder as a whole, and the module
itself by path for the helpers below it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from telethon import errors
from telethon.tl.types import Channel, ChatPhotoEmpty, User, Username, UserProfilePhoto
from telethon.tl.types import Chat as BasicGroup
from winlauncher.plugins.api import PluginContext, PluginError
from winlauncher.plugins.config import PluginConfig
from winlauncher.plugins.host import PluginHost
from winlauncher.plugins.registry import Discovery, discover_plugins

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
FOUND = discover_plugins([PLUGINS])


def plugin_module(found: Discovery, plugin_id: str) -> ModuleType:
    """The module WinLauncher loaded, so the tests use the real loading path."""
    plugin = next((p for p in found.plugins if p.id == plugin_id), None)
    if plugin is None:
        raise AssertionError(f"{plugin_id} did not load: {found.problems}")
    return sys.modules[type(plugin).__module__]


telegram = plugin_module(FOUND, "telegram")
Chat = telegram.Chat


def dialog(entity, name: str, *, message_id: int = 7, unread: int = 1):
    return SimpleNamespace(
        entity=entity, message=SimpleNamespace(id=message_id), unread_count=unread, name=name
    )


class DiscoveryTest(unittest.TestCase):
    def test_winlauncher_finds_the_plugin_folder_with_its_version(self):
        found = FOUND
        self.assertEqual(found.problems, [])
        self.assertIn("telegram", [plugin.id for plugin in found.plugins])
        source = found.sources["telegram"]
        self.assertEqual((source.origin, source.version), ("telegram", "1.1.0"))
        self.assertEqual(source.folder, PLUGINS / "telegram")
        plugin = next(plugin for plugin in found.plugins if plugin.id == "telegram")
        self.assertEqual((plugin.label, plugin.keyword), ("Telegram", "tg"))
        self.assertTrue(Path(plugin.icon).is_file())


class TelegramLinkTest(unittest.TestCase):
    def test_links_telegram_desktop_opens(self):
        chat_link = telegram.chat_link
        self.assertEqual(
            chat_link(Chat("user", 1, "Anna", username="anna_s", phone="49170")),
            "tg://resolve?domain=anna_s",
        )
        self.assertEqual(
            chat_link(Chat("user", 1, "Anna", phone="+49 170-123")), "tg://resolve?phone=49170123"
        )
        self.assertEqual(
            chat_link(Chat("supergroup", 77, "Team", last_message_id=9)),
            "tg://privatepost?channel=77&post=9",
        )
        self.assertEqual(chat_link(Chat("channel", 77, "News")), "tg://privatepost?channel=77")
        self.assertEqual(chat_link(Chat("group", 5, "Family")), "")
        self.assertEqual(chat_link(Chat("user", 5, "Hidden")), "")

    def test_items_carry_name_details_and_avatar(self):
        chat = Chat("bot", 3, "Helper", username="helperbot", unread=2)
        item = telegram.chat_item(chat, Path("C:/a.jpg"))
        self.assertEqual(
            (item.key, item.name, item.subtitle, item.keywords, item.icon),
            (
                "bot:3",
                "Helper",
                "@helperbot  ·  Bot  ·  2 unread",
                ("helperbot",),
                str(Path("C:/a.jpg")),
            ),
        )
        self.assertIsNone(telegram.chat_item(Chat("group", 5, "Family"), None))


class DialogConversionTest(unittest.TestCase):
    """Telethon's own types, so a changed API breaks a test instead of the search."""

    def test_users_bots_groups_and_channels_become_chats(self):
        as_chat = telegram._chat
        user = User(
            id=11, first_name="Anna", phone="4917012", photo=UserProfilePhoto(photo_id=99, dc_id=1)
        )
        self.assertEqual(
            as_chat(dialog(user, "Anna")),
            Chat("user", 11, "Anna", phone="4917012", last_message_id=7, unread=1, photo_id=99),
        )
        group = Channel(
            id=22,
            title="Team",
            photo=ChatPhotoEmpty(),
            date=None,
            megagroup=True,
            usernames=[Username("teamx", active=True)],
        )
        self.assertEqual(
            as_chat(dialog(group, "Team")),
            Chat("supergroup", 22, "Team", username="teamx", last_message_id=7, unread=1),
        )
        basic = BasicGroup(
            id=33,
            title="Family",
            photo=ChatPhotoEmpty(),
            participants_count=3,
            date=None,
            version=1,
        )
        self.assertEqual(as_chat(dialog(basic, "Family")).kind, "group")
        me = User(id=44, is_self=True, first_name="Me", username="me_x")
        self.assertEqual(as_chat(dialog(me, "Me")).name, "Saved Messages")
        self.assertIsNone(as_chat(dialog(User(id=55, deleted=True), "Gone")))
        self.assertIsNone(as_chat(dialog(object(), "Unknown")))


def supergroup(chat_id: int, title: str, members: int | None = None) -> Channel:
    return Channel(
        id=chat_id,
        title=title,
        photo=ChatPhotoEmpty(),
        date=None,
        megagroup=True,
        participants_count=members,
    )


def person(chat_id: int, name: str) -> User:
    return User(id=chat_id, first_name=name, username=name.lower())


class FakeClient:
    """Telethon's client as far as listing uses it: dialogs and full group info."""

    def __init__(self, dialogs, sizes=None, *, refused=(), flood_after=None):
        self.dialogs, self.sizes = dialogs, sizes or {}
        self.refused, self.flood_after = set(refused), flood_after
        self.asked: list[int] = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def is_user_authorized(self):
        return True

    async def iter_dialogs(self, **_options):
        for item in self.dialogs:
            yield item

    async def __call__(self, request):
        chat_id = request.channel.id
        if self.flood_after is not None and len(self.asked) >= self.flood_after:
            raise errors.FloodWaitError(request=None, capture=30)
        self.asked.append(chat_id)
        if chat_id in self.refused:
            raise errors.ChannelPrivateError(request=None)
        return SimpleNamespace(full_chat=SimpleNamespace(participants_count=self.sizes[chat_id]))


def options(**changes):
    defaults = {option.key: option.default for option in telegram.TelegramPlugin.options}
    return {**defaults, "avatars": False, **changes}


class Chooser:
    """Stands in for `context.choose`: records the rows and ticks the given keys."""

    def __init__(self, ticked=None):
        self.ticked = ticked
        self.shown = []

    def __call__(self, title, text, choices):
        self.shown = list(choices)
        return None if self.ticked is None else frozenset(self.ticked)


class ChatFilterTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def context(self, **changes) -> PluginContext:
        return PluginContext(data_dir=self.folder, options=options(**changes))

    def listed(self, client, **changes) -> list[str]:
        """The names a refresh lists, with `client` instead of Telegram."""
        with patch.object(telegram, "_client", return_value=client):
            items = asyncio.run(telegram.TelegramPlugin()._list(self.context(**changes), (1, "h")))
        return [item.name for item in items]

    def choose(self, chooser: Chooser) -> str | None:
        return telegram.choose_chats(replace(self.context(), choose=chooser))

    def test_groups_report_their_members(self):
        basic = BasicGroup(
            id=33,
            title="Family",
            photo=ChatPhotoEmpty(),
            participants_count=3,
            date=None,
            version=1,
        )
        self.assertEqual(telegram._chat(dialog(basic, "Family")).members, 3)
        self.assertEqual(telegram._chat(dialog(supergroup(22, "Team", 40), "Team")).members, 40)
        self.assertIsNone(telegram._chat(dialog(supergroup(22, "Team"), "Team")).members)

    def test_a_group_is_large_from_the_threshold_and_unknown_stays(self):
        is_large = telegram._is_large
        self.assertTrue(is_large(Chat("supergroup", 1, "A", members=20), 20))
        self.assertFalse(is_large(Chat("supergroup", 1, "A", members=19), 20))
        self.assertFalse(is_large(Chat("supergroup", 1, "A"), 20))
        self.assertFalse(is_large(Chat("user", 1, "A", members=500), 20))

    def test_large_groups_are_left_out_only_when_switched_on(self):
        client = FakeClient(
            [
                dialog(supergroup(1, "Big", 250), "Big"),
                dialog(supergroup(2, "Small"), "Small"),
                dialog(person(3, "Anna"), "Anna"),
            ],
            sizes={2: 4},
        )
        self.assertEqual(self.listed(client), ["Big", "Small", "Anna"])
        self.assertEqual(client.asked, [])  # Off: no group is asked for its size.
        self.assertEqual(self.listed(client, hide_large_groups=True), ["Small", "Anna"])
        self.assertEqual(
            self.listed(client, hide_large_groups=True, large_group_members=4), ["Anna"]
        )
        self.assertEqual(client.asked, [2])  # Kept for a day.

    def test_a_refused_group_stays_listed(self):
        groups = [dialog(supergroup(n, f"G{n}"), f"G{n}") for n in (1, 2, 3)]
        client = FakeClient(groups, sizes={1: 50, 3: 50}, refused={2})
        self.assertEqual(self.listed(client, hide_large_groups=True), ["G2"])

    def test_member_lookups_stop_at_the_limit_and_at_a_flood_wait(self):
        groups = [dialog(supergroup(n, f"G{n}"), f"G{n}") for n in (1, 2, 3)]
        sizes = {1: 50, 2: 50, 3: 50}
        flooded = FakeClient(groups, sizes, flood_after=1)
        self.assertEqual(self.listed(flooded, hide_large_groups=True), ["G2", "G3"])
        self.assertEqual(flooded.asked, [1])
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        limited = FakeClient(groups, sizes)
        with patch.object(telegram, "MEMBER_LOOKUPS_PER_REFRESH", 1):
            self.assertEqual(self.listed(limited, hide_large_groups=True), ["G2", "G3"])
        self.assertEqual(limited.asked, [1])

    def test_stale_counts_are_asked_again(self):
        stale = time.time() - telegram.MEMBER_COUNT_MAX_AGE_S - 1
        saved = {"1": {"members": 2, "checked": stale}}
        (self.folder / telegram.MEMBERS_FILE).write_text(json.dumps(saved), encoding="utf-8")
        client = FakeClient([dialog(supergroup(1, "Grown"), "Grown")], sizes={1: 99})
        self.assertEqual(self.listed(client, hide_large_groups=True), [])
        self.assertEqual(client.asked, [1])

    def test_unticked_chats_are_left_out_and_can_be_ticked_again(self):
        client = FakeClient(
            [dialog(person(3, "Anna"), "Anna"), dialog(supergroup(2, "Team", 5), "Team")]
        )
        self.assertEqual(self.listed(client), ["Anna", "Team"])
        chooser = Chooser({"user:3"})
        self.assertIn("1 chat left out", self.choose(chooser))
        self.assertEqual(
            [(row.key, row.detail, row.checked) for row in chooser.shown],
            [("user:3", "Person  ·  @anna", True), ("supergroup:2", "Group  ·  5 members", True)],
        )
        self.assertEqual(self.listed(client), ["Anna"])
        chooser = Chooser({"user:3", "supergroup:2"})
        self.assertEqual(self.choose(chooser), "Every chat is listed again.")
        self.assertEqual([row.checked for row in chooser.shown], [True, False])
        self.assertEqual(self.listed(client), ["Anna", "Team"])

    def test_excluding_a_result_leaves_its_chat_out_until_ticked_again(self):
        client = FakeClient(
            [dialog(person(3, "Anna"), "Anna"), dialog(supergroup(2, "Team", 5), "Team")]
        )
        self.listed(client)
        item = telegram.chat_item(Chat("supergroup", 2, "Team"), None)
        self.assertTrue(telegram.TelegramPlugin.can_exclude())
        self.assertTrue(telegram.TelegramPlugin().exclude(item, self.context()))
        self.assertEqual(self.listed(client), ["Anna"])
        chooser = Chooser()
        self.choose(chooser)
        self.assertEqual(
            [(row.key, row.checked) for row in chooser.shown][1], ("supergroup:2", False)
        )

    def test_excluded_chats_outside_the_recent_list_stay_choosable(self):
        telegram.write_excluded(self.folder, {"channel:9": "Old News"})
        chooser = Chooser()
        self.assertIsNone(self.choose(chooser))
        self.assertEqual([(row.label, row.checked) for row in chooser.shown], [("Old News", False)])

    def test_choosing_needs_a_list_and_a_host_with_checklists(self):
        self.assertIn("after the next refresh", self.choose(Chooser()))
        old_host = SimpleNamespace(data_dir=self.folder, options=options())
        with self.assertRaisesRegex(PluginError, "WinLauncher 0.17"):
            telegram.choose_chats(old_host)

    def test_a_damaged_exclusion_file_fails_visibly(self):
        (self.folder / telegram.EXCLUDED_FILE).write_text("[1, 2]", encoding="utf-8")
        with self.assertRaisesRegex(PluginError, "must map chat keys"):
            telegram.read_excluded(self.folder)


class SetupTest(unittest.TestCase):
    def test_refresh_without_sign_in_asks_for_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            host = PluginHost(FOUND, Path(directory))
            state = host.refresh("telegram", PluginConfig("telegram", enabled=True))
        self.assertTrue(state.needs_setup)
        self.assertIn("Sign in", state.error)


if __name__ == "__main__":
    unittest.main()
