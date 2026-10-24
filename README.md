# Telegram plugin for WinLauncher

Your recent Telegram chats as search results in
[WinLauncher](https://github.com/bjspi/WinLauncher). Choosing one opens that chat
in Telegram Desktop.

```text
Telegram: Anna Schmidt        @anna
Telegram: Team Annahme        Group  ·  3 unread
```

Type `tg` for your most recent chats, `tg anna` to search them, or just a name in
an ordinary search — chats appear among the files and apps.

## Install

Into the Python environment that runs WinLauncher:

```powershell
pip install -e D:\Projects\Python\WinLauncher-Plugins
```

With a pipx installation of WinLauncher:

```powershell
pipx inject winlauncher "D:\Projects\Python\WinLauncher-Plugins"
```

WinLauncher finds the plugin through the `winlauncher.plugins` entry point at its
next start. It then appears in **Settings → Plugins**.

## Sign in

Telegram Desktop keeps no chat list that another program could read: the `tdata`
folder is encrypted and holds the account key, not your chats, which the app
downloads at every start. Reading that key out of `tdata` is what session-stealing
malware does, and Telegram may end such sessions or ban the account. This plugin
therefore signs in as a session of its own, like a second device, and only reads
your chat list.

1. Create an app at [my.telegram.org](https://my.telegram.org) → *API development
   tools*. It shows an `api_id` and an `api_hash`.
2. Settings → Plugins → Telegram: turn it on, **Save**, then **Sign in…**. Enter the
   api_id, the api_hash, your phone number, the code Telegram sends to your app
   and, if you use one, your two-step verification password.

Telegram shows the session as *WinLauncher* under Settings → Devices.
**Sign out** ends it on Telegram's side too, and deletes the local session,
avatars and list. The session file
`%USERPROFILE%\.WinLauncher\plugin-data\telegram\telegram.session` grants access
to your account, like the `tdata` folder; keep it out of shared backups.

## What it lists

Up to 200 recent chats (Settings: *Chats*), in Telegram's own order. Small profile
pictures are downloaded once per photo, at most 40 per refresh, and shown as round
avatars; chats without one get colored initials. Groups, channels, bots and
archived chats can each be turned off.

Telegram Desktop opens a chat only from one of these links:

| Chat | Link |
| --- | --- |
| Anyone with a username, public group or channel | `tg://resolve?domain=<username>` |
| A person whose phone number you can see | `tg://resolve?phone=<digits>` |
| Private supergroup or channel | `tg://privatepost?channel=<id>&post=<last message>` |

Telegram Desktop has no link for basic groups or for people without a username
whose number is hidden (`tg://user?id=` does not work there), so the plugin leaves
those chats out.

## Development

```powershell
python -m ruff check winlauncher_plugin_telegram tests
python -m ruff format --check winlauncher_plugin_telegram tests
python -m unittest discover -s tests
```

The tests import `winlauncher.plugins.api`, so WinLauncher must be importable;
from a checkout, run them with `$env:PYTHONPATH = "D:\Projects\Python\WinFinder"`.
They cover link building and the conversion of Telethon's own dialog types, and
never contact Telegram. A peer kind this Telethon does not model (a newer dialog
type) is skipped, so one unknown chat cannot stop the list.

Telethon is pinned below 1.45: that release is reported to fail for accounts that
joined a Community. The plugin interface is documented in WinLauncher's
`docs/plugins.md`.
