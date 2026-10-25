"""Telegram chats as results; choosing one opens it in Telegram Desktop.

Telegram Desktop keeps no readable chat list: its `tdata` folder is encrypted and
holds the account key, not the chats, which it downloads at every start. So this
plugin signs in as a session of its own (Telethon, with the user's api_id from
my.telegram.org) and lists the chats in Telegram's order, most recent first.

Telegram Desktop opens a chat from a `tg://` link, but only by username
(`resolve?domain=`), by phone number (`resolve?phone=`) or, for supergroups and
channels, by id (`privatepost?channel=`). It has no link for basic groups or for
people without a username whose number is hidden; those chats are left out.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from winlauncher import __version__
from winlauncher.plugins.api import (
    Plugin,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    SetupRequired,
)

SESSION_NAME = "telegram"  # Telethon adds .session; the file grants access to the account.
CREDENTIALS_FILE = "api.json"
AVATAR_FOLDER = "avatars"
AVATAR_DOWNLOADS_PER_REFRESH = 40  # The rest follow in later refreshes; spares flood limits.
CONNECT_TIMEOUT_S = 15
API_HELP = (
    "Create an app at https://my.telegram.org under API development tools; "
    "it shows an api_id and an api_hash."
)
_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class Chat:
    """What a Telegram dialog tells about its chat; built from Telethon's types."""

    kind: str  # "user", "bot", "self", "group", "supergroup" or "channel".
    id: int
    name: str
    username: str = ""
    phone: str = ""
    last_message_id: int = 0
    unread: int = 0
    photo_id: int = 0


def chat_link(chat: Chat) -> str:
    """The `tg://` link Telegram Desktop opens the chat with; empty if it has none."""
    if chat.username:
        return f"tg://resolve?domain={chat.username}"
    if chat.kind in ("user", "bot", "self") and chat.phone:
        return f"tg://resolve?phone={_DIGITS.sub('', chat.phone)}"
    if chat.kind in ("supergroup", "channel"):
        post = f"&post={chat.last_message_id}" if chat.last_message_id else ""
        return f"tg://privatepost?channel={chat.id}{post}"
    return ""


_KIND_LABELS = {
    "user": "",
    "self": "Saved Messages",
    "bot": "Bot",
    "group": "Group",
    "supergroup": "Group",
    "channel": "Channel",
}


def chat_item(chat: Chat, avatar: Path | None) -> PluginItem | None:
    link = chat_link(chat)
    if not link:
        return None
    details = [f"@{chat.username}" if chat.username else "", _KIND_LABELS[chat.kind]]
    if chat.unread:
        details.append(f"{chat.unread} unread")
    return PluginItem(
        key=f"{chat.kind}:{chat.id}",
        name=chat.name,
        target=link,
        subtitle="  ·  ".join(part for part in details if part),
        keywords=(chat.username,) if chat.username else (),
        icon=str(avatar) if avatar else "",
    )


class TelegramPlugin(Plugin):
    id = "telegram"
    label = "Telegram"
    description = (
        "Your recent Telegram chats; choosing one opens it in Telegram Desktop. "
        "Needs the Python package Telethon and a sign-in with your own api_id."
    )
    keyword = "tg"
    refresh_minutes = 10
    icon = str(Path(__file__).with_name("assets") / "telegram.svg")
    round_icons = True
    options = (
        PluginOption("max_chats", "Chats", 200, "How many recent chats are listed.", (10, 2000)),
        PluginOption("groups", "Groups", True, "Also list groups."),
        PluginOption("channels", "Channels", True, "Also list channels."),
        PluginOption("bots", "Bots", True, "Also list chats with bots."),
        PluginOption("archived", "Archived chats", False, "Also list the archive."),
        PluginOption("avatars", "Profile pictures", True, "Download small profile pictures."),
    )

    def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
        credentials = _read_credentials(context.data_dir)
        if credentials is None:
            raise SetupRequired("Sign in to Telegram first.")
        return _run(self._list(context, credentials))

    def commands(self) -> tuple[PluginCommand, ...]:
        return (
            PluginCommand("Sign in…", self._sign_in),
            PluginCommand("Sign out", self._sign_out, forgets_items=True),
        )

    async def _list(self, context: PluginContext, credentials: tuple[int, str]) -> list[PluginItem]:
        client = _client(context.data_dir, credentials)
        from telethon import errors

        options = context.options
        try:
            await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT_S)
            if not await client.is_user_authorized():
                raise SetupRequired("The Telegram sign-in has ended; sign in again.")
            chats = []
            archived = None if options["archived"] else False
            async for dialog in client.iter_dialogs(
                limit=options["max_chats"], ignore_migrated=True, archived=archived
            ):
                if context.cancel.is_set():
                    return []
                chat = _chat(dialog)
                if chat is not None and _wanted(chat, options):
                    chats.append((chat, dialog.entity))
            avatars = (
                await _avatars(client, context.data_dir / AVATAR_FOLDER, chats, context)
                if options["avatars"]
                else {}
            )
        except errors.FloodWaitError as exc:
            raise PluginError(
                f"Telegram asks to wait {exc.seconds} s before listing again."
            ) from exc
        except errors.RPCError as exc:
            raise PluginError(f"Telegram refused: {exc}") from exc
        except (TimeoutError, OSError) as exc:
            raise PluginError(f"Telegram is not reachable: {exc or type(exc).__name__}") from exc
        finally:
            await client.disconnect()
        items = (chat_item(chat, avatars.get(chat.id)) for chat, _entity in chats)
        return [item for item in items if item is not None]

    def _sign_in(self, context: PluginContext) -> str | None:
        credentials = _read_credentials(context.data_dir)
        if credentials is None:
            credentials = _ask_credentials(context)
            if credentials is None:
                return None
        message = _run(_sign_in(context, credentials))
        if message is not None:
            _write_credentials(context.data_dir, credentials)
        return message

    def _sign_out(self, context: PluginContext) -> str | None:
        credentials = _read_credentials(context.data_dir)
        if credentials is not None and _session_file(context.data_dir).exists():
            _run(_sign_out(context, credentials))
        _session_file(context.data_dir).unlink(missing_ok=True)
        (context.data_dir / CREDENTIALS_FILE).unlink(missing_ok=True)
        for avatar in (context.data_dir / AVATAR_FOLDER).glob("*.jpg"):
            avatar.unlink(missing_ok=True)
        return "Signed out. WinLauncher no longer lists your Telegram chats."


def _wanted(chat: Chat, options) -> bool:
    if chat.kind in ("group", "supergroup"):
        return options["groups"]
    if chat.kind == "channel":
        return options["channels"]
    if chat.kind == "bot":
        return options["bots"]
    return True


def _chat(dialog) -> Chat | None:
    """Telethon's dialog as a `Chat`; None for deleted accounts and unknown peers."""
    from telethon.tl.types import Channel, User
    from telethon.tl.types import Chat as BasicGroup

    entity = dialog.entity
    if not isinstance(entity, User | Channel | BasicGroup):
        # A peer kind this Telethon does not model as one of the three, such as a
        # newer dialog type. Skipping it keeps the other chats listed.
        return None
    message = dialog.message
    common = {
        "id": entity.id,
        "last_message_id": getattr(message, "id", 0) or 0,
        "unread": dialog.unread_count or 0,
        "photo_id": getattr(getattr(entity, "photo", None), "photo_id", 0) or 0,
    }
    if isinstance(entity, User):
        if entity.deleted:
            return None
        kind = "self" if entity.is_self else "bot" if entity.bot else "user"
        name = "Saved Messages" if entity.is_self else dialog.name
        return Chat(kind, name=name, username=_username(entity), phone=entity.phone or "", **common)
    if isinstance(entity, Channel):
        kind = "channel" if entity.broadcast else "supergroup"
        return Chat(kind, name=dialog.name, username=_username(entity), **common)
    if isinstance(entity, BasicGroup):
        return Chat("group", name=dialog.name, **common)
    return None


def _username(entity) -> str:
    """The main username, or the first active collectible one."""
    if entity.username:
        return entity.username
    for username in getattr(entity, "usernames", None) or ():
        if username.active:
            return username.username
    return ""


async def _avatars(client, folder: Path, chats, context: PluginContext) -> dict[int, Path]:
    """Small profile pictures, downloaded once per photo; stale ones are removed."""
    folder.mkdir(parents=True, exist_ok=True)
    avatars, downloads = {}, 0
    for chat, entity in chats:
        if not chat.photo_id or not chat_link(chat):
            continue
        path = folder / f"{chat.kind}{chat.id}_{chat.photo_id}.jpg"
        if not path.exists():
            if downloads >= AVATAR_DOWNLOADS_PER_REFRESH or context.cancel.is_set():
                continue
            downloads += 1
            if (
                await client.download_profile_photo(entity, file=str(path), download_big=False)
                is None
            ):
                continue
        avatars[chat.id] = path
    kept = set(avatars.values())
    for old in folder.glob("*.jpg"):
        if old not in kept and not old.name.endswith(".tmp"):
            old.unlink(missing_ok=True)
    return avatars


async def _sign_in(context: PluginContext, credentials: tuple[int, str]) -> str | None:
    client = _client(context.data_dir, credentials)
    from telethon import errors

    try:
        await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT_S)
        if not await client.is_user_authorized():
            phone = context.ask(
                "Sign in to Telegram",
                "Your phone number in international format, such as +49 170 1234567:",
            )
            if not phone:
                return None
            sent = await client.send_code_request(phone.strip())
            code = context.ask(
                "Sign in to Telegram", "The login code Telegram sent you, usually in the app:"
            )
            if not code:
                return None
            try:
                await client.sign_in(
                    phone=phone.strip(), code=code.strip(), phone_code_hash=sent.phone_code_hash
                )
            except errors.SessionPasswordNeededError:
                password = context.ask(
                    "Sign in to Telegram", "Your two-step verification password:", secret=True
                )
                if not password:
                    return None
                await client.sign_in(password=password)
        me = await client.get_me()
    except errors.RPCError as exc:
        raise PluginError(f"Telegram refused the sign-in: {exc}") from exc
    except (TimeoutError, OSError) as exc:
        raise PluginError(f"Telegram is not reachable: {exc or type(exc).__name__}") from exc
    finally:
        await client.disconnect()
    name = " ".join(part for part in (me.first_name, me.last_name) if part) or "your account"
    return f"Signed in as {name}. Your chats appear after the next refresh."


async def _sign_out(context: PluginContext, credentials: tuple[int, str]) -> None:
    client = _client(context.data_dir, credentials)
    try:
        await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT_S)
        if await client.is_user_authorized():
            await client.log_out()  # Ends the session on Telegram's side, too.
    except Exception as exc:
        context.log.info("Telegram sign-out only removed the local session: %s", exc)
    finally:
        await client.disconnect()


def _client(folder: Path, credentials: tuple[int, str]):
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SetupRequired(
            "Install the Python package Telethon: pip install telethon "
            "(pipx: pipx inject winlauncher telethon)."
        ) from exc
    api_id, api_hash = credentials
    return TelegramClient(
        str(folder / SESSION_NAME),
        api_id,
        api_hash,
        device_model="WinLauncher",
        system_version="Windows",
        app_version=__version__,
        receive_updates=False,
    )


def _run(coroutine):
    """Run Telethon on a fresh event loop of the calling worker thread."""
    return asyncio.run(coroutine)


def _session_file(folder: Path) -> Path:
    return folder / f"{SESSION_NAME}.session"


def _read_credentials(folder: Path) -> tuple[int, str] | None:
    try:
        data = json.loads((folder / CREDENTIALS_FILE).read_text(encoding="utf-8"))
        api_id, api_hash = data["api_id"], data["api_hash"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if type(api_id) is not int or not isinstance(api_hash, str) or not api_hash:
        return None
    return api_id, api_hash


def _write_credentials(folder: Path, credentials: tuple[int, str]) -> None:
    api_id, api_hash = credentials
    text = json.dumps({"api_id": api_id, "api_hash": api_hash})
    (folder / CREDENTIALS_FILE).write_text(text, encoding="utf-8")


def _ask_credentials(context: PluginContext) -> tuple[int, str] | None:
    api_id = context.ask("Telegram api_id", f"{API_HELP}\n\napi_id:")
    if not api_id:
        return None
    if not api_id.strip().isdigit():
        raise PluginError("The api_id is a number, such as 1234567.")
    api_hash = context.ask("Telegram api_hash", "api_hash:", secret=True)
    if not api_hash:
        return None
    return int(api_id.strip()), api_hash.strip()
