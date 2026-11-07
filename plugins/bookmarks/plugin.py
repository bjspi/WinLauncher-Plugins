"""Adapt WinLauncher's standalone-file loader to a private implementation package.

The host gives plugin.py a unique module name but no package search path. Load a
normal package under that name so relative imports work without changing sys.path
or colliding with another copy of this plugin.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_implementation() -> ModuleType:
    package = Path(__file__).with_name("bookmark_plugin") / "__init__.py"
    name = f"{__name__.replace('.', '_')}_implementation"
    spec = importlib.util.spec_from_file_location(name, package)
    if spec is None or spec.loader is None:
        raise ImportError("Could not load the Bookmarks implementation.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        for loaded in tuple(sys.modules):
            if loaded == name or loaded.startswith(name + "."):
                sys.modules.pop(loaded, None)
        raise
    return module


_implementation = _load_implementation()


class BookmarksPlugin(_implementation.BookmarksPlugin):
    """The locally defined subclass WinLauncher's discovery expects."""
