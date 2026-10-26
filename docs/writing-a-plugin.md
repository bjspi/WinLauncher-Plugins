# Writing a plugin

A plugin brings items from another program into WinLauncher's search bar: chats,
contacts, tickets, records. WinLauncher searches them with the same matching as
file names and asks the plugin to open the one you chose, usually through a deep
link into its application.

This is the practical guide for this repository. The behavior of the host — how
items are ranked, when plugins answer a query, which threads call you — is
specified in WinLauncher's
[docs/plugins.md](https://github.com/bjspi/WinLauncher/blob/main/docs/plugins.md).

## Start from the template

```powershell
Copy-Item -Recurse plugins\_template plugins\myplugin
```

A plugin is a folder, and nothing else is registered anywhere:

```text
plugins\myplugin\
    plugin.toml      version, name, description, requires ← read without running your code
    plugin.py        your Plugin subclass
    assets\          icons and other files that belong to the plugin
```

WinLauncher imports `plugin.py` once at start and takes every `Plugin` subclass
the file defines itself. Restart WinLauncher from the tray to load a change.

### The manifest

`plugin.toml` is what WinLauncher knows before it runs any of your code: Settings
shows the installed version, and the catalog lists your plugin with it.

```toml
version = "1.0.0"
name = "Telegram"                        # The catalog's entry; your label once loaded.
description = "Your recent Telegram chats; choosing one opens it in Telegram Desktop."
requires = ["telethon>=1.34,<1.45"]      # Packages beside WinLauncher, as pip requirements.
```

Every field is optional, but a plugin without a `version` is never offered an
update. WinLauncher does not install `requires` itself; it shows the user the
`pipx inject` or `pip install` command for their installation.

### Publishing

This repository is a **plugin catalog**: `catalog.toml` at its root names it and
its `plugins` folder, and WinLauncher offers every folder in there (except those
starting with `_`) under Settings → Plugins → Available plugins. Pushing a plugin
with a raised `version` is the release: installed copies are offered the update
within 6 hours. A company or team catalog works the same way — a repository of its
own with a `catalog.toml`, added under **Plugin catalogs** in WinLauncher's
settings.

## The entry points

Everything WinLauncher calls is on your `Plugin` subclass. Only `id`, `label` and
`refresh` are required.

### What you declare

| Attribute | Meaning |
| --- | --- |
| `id` | Settings key and data folder name; `a-z`, `0-9`, `_`, `-`. Must stay stable: it ties the user's settings and cache to your plugin. |
| `label` | Shown before each item's name, as in `Telegram: Anna`. |
| `description` | One or two sentences for the settings card. |
| `keyword` | Typed first, it puts your items on top (`tg anna`); the same text still searches files, and `@tg anna` answers from your plugin alone. The user may change it. |
| `refresh_minutes` | How often `refresh` runs, 1 to 1440. |
| `icon` | Image file for items that bring no icon of their own. |
| `round_icons` | `True` for avatars: images are cropped to circles, and items without one get colored initials. |
| `options` | `PluginOption` values the user edits in Settings; their type is the type of `default`. |
| `literal_terms` | Patterns for typed terms that name one of your items, such as `(r"HCP-?\w*",)`. A term one of them describes entirely is matched in one piece instead of loosely. Case is ignored. |

### What you implement

```python
def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
```
Return **every** item, most relevant first — for chats, the one written to last.
Runs on a worker thread at the configured interval and may take seconds.
WinLauncher keeps the result, searches it locally on every keystroke and caches it
for the next start, so this is not called per search. Raise `PluginError` with a
message for the user when it fails, or `SetupRequired` when the user must sign in
or configure something first.

```python
def open(self, item: PluginItem, context: PluginContext) -> None:
```
Open the chosen item. The default hands `item.target` to Windows
(`os.startfile`), so a URI such as `tg://…`, `msteams:/…`, `mailto:` or
`https://…`, or a plain file path, opens in its registered program. Override it
only when opening needs more than that. Runs on the action worker.

```python
def commands(self) -> tuple[PluginCommand, ...]:
```
Buttons for your settings card, such as *Sign in…*. `PluginCommand(label, run)`;
`run(context)` may ask the user for one line of text with
`context.ask(title, text, secret=False)` and returns a message to show. With
`forgets_items=True` the cached list is dropped afterwards, as *Sign out* needs.

### What an item carries

`PluginItem(key, name, target, subtitle, keywords, icon, title, data)`

- `key` identifies the item across refreshes; keep it stable.
- `name` is what the typed words are matched against.
- `keywords` also find the item — a username, an email address — and rank a little
  below a name match.
- `subtitle` is the muted text beside the name, `title` replaces the whole
  `Label: name` text, `icon` is an image file such as a cached avatar.
- `data` holds JSON values your `open` needs; it is cached and never matched.

### What the context gives you

- `context.data_dir` — your own folder for caches, sessions and downloaded
  pictures. **Everything you write belongs here**, never next to your code, so the
  plugin folder stays a clean checkout.
- `context.options` — the user's values for your `options`, already validated; an
  invalid one falls back to your default.
- `context.cancel` — a `threading.Event`. A long refresh must check it and return
  early when it is set.
- `context.log` — writes to WinLauncher's log under `winlauncher.plugins.<id>`.
- `context.ask` — only available in commands; a background refresh raises
  `SetupRequired` instead.

## Rules that matter

**Never break the host.** WinLauncher checks what you declare when it loads your
plugin and refuses a plugin whose metadata is unusable, instead of failing later
while painting results. Every call into your plugin is wrapped: an exception in
`refresh` is shown on the settings card and keeps the previously listed items, and
one in `open` or a command is reported as a failed action. A syntax error means
your plugin is listed as *not loaded* and the rest of WinLauncher starts normally.

**Return.** The one thing WinLauncher cannot do for you is interrupt you: Python
cannot kill a running thread. Two plugins stuck in `refresh` occupy both plugin
workers, and no plugin refreshes until they return. So give every network call and
every subprocess an explicit timeout, and honor `context.cancel`.

**Bring no dependencies.** A plugin folder installs nothing. Import the standard
library, WinLauncher's own API and packages that are already in the environment
running WinLauncher. When one is missing, catch the `ImportError` and raise
`SetupRequired` with the command that installs it:

```python
try:
    import telethon
except ImportError as exc:
    raise SetupRequired("Install Telethon: pip install telethon") from exc
```

**Keep secrets out of the settings file.** `options` are stored in plain text in
`settings.json`. Tokens, passwords and session files belong in
`context.data_dir`, written by a command of your own, as the Telegram plugin does
with its `api.json`.

**Be cheap per keystroke.** Searching happens locally on the list you returned, so
`refresh` is the only place that talks to the network. Cache what is expensive
(avatars by photo id, for instance) and re-fetch only what changed.

**Know the size you can afford.** Matching runs in Python over your list. A few
thousand items stay inside a keystroke — 5,000 tickets answer a typical query in
13 to 45 ms, a number in 2 ms — but tens of thousands do not. List the part of your
world that is actually searched by name, and offer the rest through a direct
lookup: recognize an identifier in the typed text and return one item that opens
it, without asking any server.

You do not choose how your items are matched; WinLauncher matches them like file
names, which is why a chat ranks against files sensibly and matched letters are
highlighted. What you do decide is which typed terms name an item rather than
describe one. A term containing a digit always counts as a name, so `12345` finds
ticket 12345 and not 52314. For identifiers without digits, declare their shape:

```python
literal_terms = (r"HCP-?\w*",)   # HCP and HCP-1234 are names, not words
```

Only the terms a pattern describes entirely are affected; the words of the same
query keep matching loosely, so `HCP calibratio` still finds a typo'd title.

**Threads.** `refresh`, `open` and commands run on different worker threads, never
the GUI thread. A plugin that uses COM calls `pythoncom.CoInitialize()` at the
start of each of them and `pythoncom.CoUninitialize()` when done.

## Checklist before committing a plugin

- [ ] `plugin.toml` names a new `version`, and its `name`, `description` and
      `requires` still fit.
- [ ] `id` unchanged, `label` set, `description` one or two sentences.
- [ ] Every network call and subprocess has a timeout; `context.cancel` is honored.
- [ ] Failures raise `PluginError`/`SetupRequired` with a message a user understands.
- [ ] Nothing is written outside `context.data_dir`; no secret in `options`.
- [ ] `python -m ruff check plugins tests` and `ruff format --check` pass.
- [ ] Tests cover link building and the conversion of foreign data, and contact no
      server.
