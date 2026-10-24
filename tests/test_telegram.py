"""Links, items and dialog conversion; no test contacts Telegram."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from telethon.tl.types import Channel, ChatPhotoEmpty, User, Username, UserProfilePhoto
from telethon.tl.types import Chat as BasicGroup
from winlauncher.plugins.config import PluginConfig
from winlauncher.plugins.host import PluginHost

from winlauncher_plugin_telegram.plugin import Chat, TelegramPlugin, _chat, chat_item, chat_link


def dialog(entity, name: str, *, message_id: int = 7, unread: int = 1):
    return SimpleNamespace(
        entity=entity, message=SimpleNamespace(id=message_id), unread_count=unread, name=name
    )


class TelegramLinkTest(unittest.TestCase):
    def test_links_telegram_desktop_opens(self):
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
        item = chat_item(chat, Path("C:/a.jpg"))
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
        self.assertIsNone(chat_item(Chat("group", 5, "Family"), None))


class DialogConversionTest(unittest.TestCase):
    """Telethon's own types, so a changed API breaks a test instead of the search."""

    def test_users_bots_groups_and_channels_become_chats(self):
        user = User(
            id=11,
            first_name="Anna",
            phone="4917012",
            photo=UserProfilePhoto(photo_id=99, dc_id=1),
        )
        self.assertEqual(
            _chat(dialog(user, "Anna")),
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
            _chat(dialog(group, "Team")),
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
        self.assertEqual(_chat(dialog(basic, "Family")).kind, "group")
        me = User(id=44, is_self=True, first_name="Me", username="me_x")
        self.assertEqual(_chat(dialog(me, "Me")).name, "Saved Messages")
        self.assertIsNone(_chat(dialog(User(id=55, deleted=True), "Gone")))
        self.assertIsNone(_chat(dialog(object(), "Unknown")))


class SetupTest(unittest.TestCase):
    def test_refresh_without_sign_in_asks_for_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            host = PluginHost([TelegramPlugin()], Path(directory))
            state = host.refresh("telegram", PluginConfig("telegram", enabled=True))
        self.assertTrue(state.needs_setup)
        self.assertIn("Sign in", state.error)


if __name__ == "__main__":
    unittest.main()
