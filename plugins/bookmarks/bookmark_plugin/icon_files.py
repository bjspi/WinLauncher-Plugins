"""Keep the cached icons as image files, which is what WinLauncher shows beside an item."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .domain import IconImage

ICONS_FOLDER = "icons"
NAME_LENGTH = 32  # Hex digits of the content's hash: equal icons share one file.
TEMPORARY_SUFFIX = ".tmp"
# Formats WinLauncher can draw, recognized by their first bytes.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\x00\x00\x01\x00", ".ico"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"\xff\xd8\xff", ".jpg"),
)
WEBP_CONTAINER, WEBP_FORMAT, WEBP_FORMAT_AT = b"RIFF", b"WEBP", slice(8, 12)
SVG_HEAD_BYTES = 1024
SVG_LEADING = b"\xef\xbb\xbf \t\r\n"  # A byte order mark and whitespace before the markup.


class IconFiles:
    """One file per distinct icon in the plugin's data folder, and nothing it no longer uses."""

    def __init__(self, data_dir: Path) -> None:
        self.folder = data_dir / ICONS_FOLDER
        self._used: set[Path] = set()

    def path_for(self, image: IconImage | None) -> str:
        """The file showing `image`; empty for none, or one in a format WinLauncher cannot draw."""
        suffix = image_suffix(image.data) if image is not None else None
        if image is None or suffix is None:
            return ""
        path = self.folder / (hashlib.sha256(image.data).hexdigest()[:NAME_LENGTH] + suffix)
        try:
            if not path.exists():
                self._write(path, image.data)
        except OSError:
            return ""
        self._used.add(path)
        return str(path)

    def remove_unused(self) -> None:
        """Delete the icons of bookmarks that are gone; call it after a complete refresh."""
        if not self.folder.is_dir():
            return
        for file in self.folder.iterdir():
            if file not in self._used:
                file.unlink(missing_ok=True)

    def _write(self, path: Path, data: bytes) -> None:
        """Replace atomically, so WinLauncher never draws half a file."""
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + TEMPORARY_SUFFIX)
        temporary.write_bytes(data)
        temporary.replace(path)


def image_suffix(data: bytes) -> str | None:
    """The file suffix of an image format WinLauncher draws; None for anything else."""
    for signature, suffix in SIGNATURES:
        if data.startswith(signature):
            return suffix
    if data.startswith(WEBP_CONTAINER) and data[WEBP_FORMAT_AT] == WEBP_FORMAT:
        return ".webp"
    head = data[:SVG_HEAD_BYTES].lstrip(SVG_LEADING).lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return ".svg"
    return None
