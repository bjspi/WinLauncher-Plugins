"""A starting point for a plugin: copy this folder and rename it.

Folders whose name starts with `_` are not loaded, so this template never shows up
in WinLauncher. See ../../docs/writing-a-plugin.md for the full interface.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from winlauncher.plugins.api import (
    Plugin,
    PluginContext,
    PluginError,
    PluginItem,
    PluginOption,
    PluginRoute,
)

MAX_ITEMS = 200
DRAFTS_ROUTE = "drafts"
DRAFT_PREFIX = "draft"  # Notes whose file name starts with it are drafts.


class TemplatePlugin(Plugin):
    id = "template"  # Keep this stable: the user's settings and cache hang on it.
    label = "Note"  # Rows read "Note: <name>".
    description = "What this plugin lists, in one or two sentences."
    keywords = ("n", "note")  # "n shopping" puts this plugin first; synonyms work alike.
    # A second way in: "draft shopping" searches only the items routed to it.
    routes = (PluginRoute(DRAFTS_ROUTE, "Drafts only", ("draft",)),)
    refresh_minutes = 15
    icon = str(Path(__file__).with_name("assets") / "icon.svg")
    round_icons = False  # True for people: round avatars and colored initials.
    options = (
        PluginOption("folder", "Folder", r"C:\Notes", "Where the notes are."),
        PluginOption("limit", "Items", 50, "How many to list.", (1, MAX_ITEMS)),
    )

    def refresh(self, context: PluginContext) -> Iterable[PluginItem]:
        """Every item, most relevant first. Runs on a worker; may take seconds.

        Give network calls and subprocesses a timeout, and stop early when
        `context.cancel` is set: WinLauncher cannot interrupt a running plugin.
        """
        folder = Path(str(context.options["folder"]))
        if not folder.is_dir():
            raise PluginError(f"{folder} does not exist. Choose another folder in Settings.")
        try:
            files = sorted(folder.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError as exc:
            raise PluginError(f"{folder} could not be read: {exc.strerror or exc}") from exc
        items = []
        for file in files[: int(context.options["limit"])]:
            if context.cancel.is_set():
                return []
            items.append(
                PluginItem(
                    key=str(file),
                    name=file.stem,
                    target=str(file),  # Opened with os.startfile by default.
                    subtitle=str(file.parent),
                    routes=(DRAFTS_ROUTE,) if file.stem.lower().startswith(DRAFT_PREFIX) else (),
                )
            )
        return items
