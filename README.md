<div align="center">

<img src="https://raw.githubusercontent.com/bjspi/WinLauncher/main/docs/images/icon.png" width="96" alt="WinLauncher icon">

# WinLauncher Plugins

**Your chats, contacts and records — right in the search bar.**

Search plugins for [WinLauncher](https://github.com/bjspi/WinLauncher): items from other
programs show up next to your files and apps, and open by a deep link straight into
their own application.

[![WinLauncher 0.12+](https://img.shields.io/badge/WinLauncher-0.12%2B-0078D6?logo=windows&logoColor=white)](https://github.com/bjspi/WinLauncher)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![One-click install](https://img.shields.io/badge/Install-one%20click%20in%20Settings-41CD52)](#-install)
[![Ruff](https://img.shields.io/badge/code%20style-Ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![License: MIT](https://img.shields.io/badge/License-MIT-F7DF1E)](LICENSE)

</div>

Typing `tg anna` in WinLauncher:

```text
Telegram: Anna Schmidt        @anna
Telegram: Team Annahme        Group  ·  3 unread
annual-report.pdf             D:\Documents\2026
```

---

## 🧩 Plugins

| Plugin | What it lists | Keyword |
| --- | --- | --- |
| <img src="plugins/telegram/assets/telegram.svg" width="16"> [**Telegram**](#-telegram) | Your recent Telegram chats, opened in Telegram Desktop | `tg` |
| 📐 [`_template`](plugins/_template) | Not a plugin: the skeleton to copy for a new one | — |

## ✨ How it feels

| | |
| --- | --- |
| ⌨️ **Keyword on top** | `tg anna` puts matching chats first — your files still follow below, so `tg` never swallows a word. |
| 🎯 **`@` for one plugin alone** | `@tg anna` answers from Telegram only, without any file results. |
| 🔍 **Same smart matching** | Prefixes, word starts, initials and fuzzy matches, exactly like file names. Identifiers such as ticket numbers are matched literally. |
| 📦 **One-click install** | Install, update and remove plugins right in WinLauncher's settings; new versions are announced. |
| ⚡ **Never costs a keystroke** | Plugins refresh in the background and are searched locally; their last list is cached across restarts and offline. |
| 🛡️ **Can't break WinLauncher** | A plugin that fails to import, declares nonsense or throws is listed as a problem — everything else keeps running. |
| 🔒 **Yours stay private** | Private plugins live in your own folder and take precedence over same-named ones here. |

## 📦 Install

This repository is WinLauncher's default **plugin catalog**, so there is nothing to
download by hand:

1. WinLauncher → **Settings → Plugins → Available plugins**: choose a plugin, **Install**.
2. Restart WinLauncher from the tray, then turn the plugin on in its settings.

WinLauncher checks the catalog every 6 hours and announces new versions of installed
plugins; **Update** installs them. Catalogs need [git](https://git-scm.com/).

**Working on plugins?** Clone this repository and add its `plugins` folder under
Settings → Plugins → **Plugin folders** instead; WinLauncher then loads the plugins
straight from your clone.

## 🏢 Your own catalog

Any git repository becomes a catalog with a `catalog.toml` at its root — handy for a
team's private plugins on a company git server:

```toml
name = "Team plugins"
plugins = "plugins"     # One subfolder per plugin, each with plugin.py and plugin.toml.
```

Add its address under Settings → Plugins → **Plugin catalogs**. Private repositories
use your saved git credentials. Each plugin folder names its version, name,
description and required packages in its `plugin.toml`
([the manifest](docs/writing-a-plugin.md#the-manifest)).

## 💬 Telegram

Lists your recent Telegram chats; choosing one opens that chat in Telegram Desktop.
Type `tg` for the most recent ones, `tg anna` to search them, `@tg anna` for chats
without any file results, or just a name in an ordinary search.

### Why it signs in on its own

Telegram Desktop keeps no chat list that another program could read: the `tdata`
folder is encrypted and holds the account key, not your chats, which the app
downloads at every start. Reading that key out of `tdata` is what session-stealing
malware does, and Telegram may end such sessions or ban the account. This plugin
therefore signs in as a session of its own, like a second device, and only reads
your chat list.

### Setup

1. Install [Telethon](https://pypi.org/project/Telethon/) into the environment
   that runs WinLauncher: `pip install "telethon>=1.34,<1.45"`, or
   `pipx inject winlauncher "telethon>=1.34,<1.45"` for a pipx installation.
   1.45 is reported to fail for accounts that joined a Community.
2. Create an app at [my.telegram.org](https://my.telegram.org) → *API development
   tools*. It shows an `api_id` and an `api_hash`.
3. Settings → Plugins → Telegram: turn it on, **Save**, then **Sign in…**. Enter the
   api_id, the api_hash, your phone number, the code Telegram sends to your app
   and, if you use one, your two-step verification password.

Telegram shows the session as *WinLauncher* under Settings → Devices.
**Sign out** ends it on Telegram's side too, and deletes the local session,
avatars and list.

> [!WARNING]
> The session file `%USERPROFILE%\.WinLauncher\plugin-data\telegram\telegram.session`
> grants access to your account, like the `tdata` folder. Keep it out of shared backups.

### What you get

Up to 200 recent chats are listed (Settings: *Chats*), in Telegram's own order.
Small profile pictures are downloaded once per photo, at most 40 per refresh, and
shown as round avatars; chats without one get colored initials. Groups, channels,
bots and archived chats can each be turned off. Telegram Desktop opens a chat only
from one of these links:

| Chat | Link |
| --- | --- |
| Anyone with a username, public group or channel | `tg://resolve?domain=<username>` |
| A person whose phone number you can see | `tg://resolve?phone=<digits>` |
| Private supergroup or channel | `tg://privatepost?channel=<id>&post=<last message>` |

Telegram Desktop has no link for basic groups or for people without a username
whose number is hidden (`tg://user?id=` does not work there), so the plugin leaves
those chats out. A peer kind the installed Telethon does not model is skipped, so
one unknown chat cannot stop the list.

## 🛠️ Write your own

```powershell
Copy-Item -Recurse plugins\_template plugins\myplugin
```

A plugin needs only an `id`, a `label` and a `refresh` that returns its items —
WinLauncher does the matching, ranking, caching and scheduling. Folders whose name
begins with `_` are not loaded.

- 📖 [docs/writing-a-plugin.md](docs/writing-a-plugin.md) — the guide: entry points,
  the rules that matter and a checklist.
- 📐 WinLauncher's [docs/plugins.md](https://github.com/bjspi/WinLauncher/blob/main/docs/plugins.md)
  — how the host ranks, schedules and opens items.

### Checks

```powershell
python -m ruff check plugins tests
python -m ruff format --check plugins tests
$env:PYTHONPATH = "<path to your WinLauncher checkout>"; python -m unittest discover -s tests
```

The tests load the plugins the way WinLauncher does and never contact Telegram.
`PYTHONPATH` only has to name WinLauncher's checkout while it is not installed as
a package.

## 📄 License

[MIT](LICENSE)
