"""Links, items and dialog conversion; no test contacts Telegram.

The plugin is a folder, not an installed package, so the module is loaded the way
WinLauncher loads it: `discover_plugins` for the folder as a whole, and the module
itself by path for the helpers below it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

from telethon.tl.types import Channel, ChatPhotoEmpty, User, Username, UserProfilePhoto
from telethon.tl.types import Chat as BasicGroup
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
        self.assertEqual([plugin.id for plugin in found.plugins], ["telegram"])
        source = found.sources["telegram"]
        self.assertEqual((source.origin, source.version), ("telegram", "1.0.0"))
        self.assertEqual(source.folder, PLUGINS / "telegram")
        plugin = found.plugins[0]
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


class SetupTest(unittest.TestCase):
    def test_refresh_without_sign_in_asks_for_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            host = PluginHost(FOUND, Path(directory))
            state = host.refresh("telegram", PluginConfig("telegram", enabled=True))
        self.assertTrue(state.needs_setup)
        self.assertIn("Sign in", state.error)


if __name__ == "__main__":
    unittest.main()
