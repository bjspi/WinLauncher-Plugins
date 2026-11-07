# AI Sessions

Find local **Codex**, **Claude Code** and **GitHub Copilot CLI** conversations and
resume a selected session in its project directory. Every result shows its session
name, working directory and the provider's original logo.

Activate **AI Sessions** under Settings → Plugins → Available plugins. If working
from this checkout, add the checkout as a plugin source first. Activation installs
PyYAML for Copilot's workspace metadata. Restart WinLauncher after activation.

## Search and resume

| Query | Results |
| --- | --- |
| `ai` or `sessions` | Recent sessions from all three providers |
| `codex launcher` | Matching Codex sessions first |
| `claude launcher` | Matching Claude Code sessions first |
| `copilot launcher` | Matching Copilot CLI sessions first |
| `@claude launcher` | Matching Claude Code sessions, without file results |

Session titles, working directories and session IDs are searchable. A chosen
session name takes precedence over an automatic title where the local format
exposes it; otherwise the first user message or the session ID supplies a title.
Sessions are ordered by their last known activity, newest first, and each row shows
it in local time as a chip before the working directory: `Today 13:09`,
`Yesterday 09:12` or `2026-11-02 18:40`.
Chips need WinLauncher 0.15.10 or newer.

Opening a result starts a new Windows Terminal window in the session's project
directory, using PowerShell and the corresponding command:

```text
codex resume <session-id>
claude --resume <session-id>
copilot --resume <session-id>
```

Without Windows Terminal, a visible PowerShell console opens instead. The CLI
must be available on WinLauncher's `PATH`. A missing CLI, PowerShell or project
directory produces an action error with an explanation. Refresh never launches
a CLI, contacts a service or requires all three tools to be installed.

This covers local CLI histories, including locally recorded Codex editor
sessions. It does not read VS Code's separate GitHub Copilot Chat history or
remote-only conversations.

## Filters and exclusions

Settings → Plugins → AI Sessions offers:

| Setting | Default | Meaning |
| --- | --- | --- |
| Last active within (days) | **14** | A rolling age window; `7` means the last week, `0` includes all ages |
| Sessions | **300** | Maximum visible sessions across the three providers, up to 2,000 |
| Excluded session names | Empty | One `fnmatch` pattern per line, ignoring case |
| Codex / Claude Code / Copilot CLI | On | Enable or disable each provider |
| Provider folders | Empty | Override the local configuration directory |

The age window and exclusions apply before the count limit. The list refreshes
every minute by default; WinLauncher can change that interval. Codex uses its
index's activity timestamp. Claude Code and Copilot use the latest sampled user
or assistant message timestamp. Older records without usable timestamps fall
back to the transcript's modification time. Editing title metadata alone does
not refresh a Claude or Copilot conversation's message timestamp.

**Excluded session names** hides every session whose shown title matches a pattern
as a whole: `*probe*` anywhere in the title, `Resume ?revious task` with one wildcard
character, `[abc]*` for a set of first letters. Removing the line shows those sessions
again; **Restore session…** does not list them.

**Right-click a session → Exclude…** (WinLauncher 0.17 or newer) offers *Only this
session*, ticked, and *Every session in* its project folder and up to two folders
above it, never a whole drive. A folder hides every session started in it or
below it, also later ones. The same menu has **Open project folder**, which shows
the session's folder in Explorer.

**Exclude session…** on the settings card searches by title, project, provider or
ID and then asks for the number of the exact session to hide, among at most eight
matches. **Restore session…** brings back a session or a folder, found by its
title, project or folder.

Exclusions survive refreshes, restarts, renames and plugin updates. Sessions are
keyed by `provider:session-id`, folders by `folder:<path>`, compared ignoring case
and slash direction; all are stored atomically in
`%USERPROFILE%\.WinLauncher\plugin-data\ai_sessions\excluded-sessions.json`
with a short description for restoring them. Neither excluding nor restoring a
session changes its conversation files. The host discards its cached list after
either command and refreshes it. A restored session still needs to meet the age
and count filters.

## Local sources

| Provider | Default directory | Data read |
| --- | --- | --- |
| Codex | `CODEX_HOME` or `~/.codex` | Latest `state_*.sqlite` metadata, with `sessions/**/*.jsonl` and `session_index.jsonl` as a fallback |
| Claude Code | `CLAUDE_CONFIG_DIR` or `~/.claude` | `projects/*/*.jsonl`, excluding nested subagents and sidechains |
| Copilot CLI | `COPILOT_HOME` or `~/.copilot` | `session-state/*/events.jsonl` and `workspace.yaml`, plus optional summaries from `session-store.db` |

A configured provider folder overrides the environment and default. For a custom
home, resuming sets the same CLI home variable in the new terminal, so it does not
accidentally resume against another history. A default installation is left without
the variable: with `CLAUDE_CONFIG_DIR` set, Claude Code moves `.claude.json` from the
profile into that folder and would start without the user's global state.

SQLite connections use read-only mode and a one-second lock timeout. Transcript
readers sample at most 128 KiB from each end of a file; they do not load entire
large conversations. Invalid JSON records are skipped. Missing providers yield
no sessions, and a filesystem or SQLite failure in one provider is logged while
the others remain available. Codex archived sessions, internal subagents and
non-interactive `exec` sessions are omitted, as are Claude Code's non-interactive
runs (`claude -p`, the Agent SDK) and transcripts without a message. Titles from
first messages skip Claude Code's injected context and slash-command markup. Codex's
`\\?\` long-path prefix is removed from project folders, because a process started
in such a folder would run in the Windows folder instead. A damaged exclusions file
raises a plugin error instead of silently showing previously hidden sessions again.

## Architecture

```text
plugins/ai_sessions/
  plugin.py                        Host discovery entry point only
  plugin.toml                      Catalog metadata
  assets/                          Provider logos, source attribution and license
  session_plugin/
    application.py                 Host settings, items and workflow orchestration
    domain.py                      Immutable values, identity and visibility policy
    catalog.py                     Source resolution and provider isolation
    exclusions.py                  Durable exclusion storage and explicit selection
    terminal.py                    Windows terminal and CLI integration
    readers/
      records.py                   Bounded JSONL reads and read-only SQLite access
      codex.py                     Codex format adapter
      claude.py                    Claude Code format adapter
      copilot.py                   Copilot CLI format adapter
```

Only `application.py` imports the WinLauncher API. Domain values and filtering
have no dependency on the host, filesystem operations or subprocesses. Readers
return `Session` values; exclusions and terminal code report `SessionError`,
which the application translates into the host's `PluginError`.

WinLauncher currently imports `plugin.py` as a standalone module. The entry point
therefore loads a normal private package under a unique name derived from the
host's module name. A locally declared subclass satisfies host discovery. This
keeps normal relative imports inside the implementation, avoids modifying
`sys.path`, and isolates two loaded copies of the plugin. No host changes or
extra package installation are required.

Tests load through WinLauncher's real discovery and host APIs and cover provider
formats, routes, age and count filters, exclusion persistence, missing tools and
terminal arguments. One test runs the resume script in a real PowerShell against a
stand-in CLI. They start no interactive AI sessions.
