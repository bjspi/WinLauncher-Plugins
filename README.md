# WinLauncher plugins

Search plugins for [WinLauncher](https://github.com/bjspi/WinLauncher): chats,
contacts and records of other programs as search results, each opened by a deep
link into its own application.

| Plugin | What it lists |
| --- | --- |
| [`telegram`](plugins/telegram) | Your recent Telegram chats, opened in Telegram Desktop |

Every plugin is one folder under `plugins/`, holding `plugin.py`, a `plugin.toml`
with its version and whatever assets it needs. WinLauncher loads such folders
directly, so nothing here is installed with pip.

## Use them

Clone this repository and point WinLauncher at its `plugins` folder:

```powershell
git clone https://github.com/bjspi/WinLauncher-Plugins.git D:\Projects\Python\WinLauncher-Plugins
```

Settings → Plugins → **Plugin folders**: add `D:\Projects\Python\WinLauncher-Plugins\plugins`,
save and restart WinLauncher from the tray. Each plugin then appears on the
Plugins page, off until you turn it on.

To take a single plugin instead, copy its folder into
`%USERPROFILE%\.WinLauncher\plugins\`, which WinLauncher always searches. The same
folder is the place for private plugins of your own, which are never pushed here.

## Telegram

Lists your recent Telegram chats; choosing one opens that chat in Telegram
Desktop. Type `tg` for the most recent ones, `tg anna` to search them, or just a
name in an ordinary search.

```text
Telegram: Anna Schmidt        @anna
Telegram: Team Annahme        Group  ·  3 unread
```

Telegram Desktop keeps no chat list that another program could read: the `tdata`
folder is encrypted and holds the account key, not your chats, which the app
downloads at every start. Reading that key out of `tdata` is what session-stealing
malware does, and Telegram may end such sessions or ban the account. This plugin
therefore signs in as a session of its own, like a second device, and only reads
your chat list.

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
avatars and list. The session file
`%USERPROFILE%\.WinLauncher\plugin-data\telegram\telegram.session` grants access
to your account, like the `tdata` folder; keep it out of shared backups.

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

## Develop

Writing a plugin is documented in WinLauncher's
[docs/plugins.md](https://github.com/bjspi/WinLauncher/blob/main/docs/plugins.md).

```powershell
python -m ruff check plugins tests
python -m ruff format --check plugins tests
$env:PYTHONPATH = "D:\Projects\Python\WinFinder"; python -m unittest discover -s tests
```

The tests load the plugins the way WinLauncher does and never contact Telegram.
`PYTHONPATH` only has to name WinLauncher's checkout while it is not installed as
a package.
