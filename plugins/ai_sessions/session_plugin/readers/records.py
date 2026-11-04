"""Bounded transcript sampling and read-only metadata database access."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

SAMPLE_BYTES = 128 * 1024
SQLITE_TIMEOUT_SECONDS = 1
LONG_PATH_PREFIX = "\\\\?\\"
LONG_UNC_PREFIX = LONG_PATH_PREFIX + "UNC\\"
UNC_PREFIX = "\\\\"
TEXT_BLOCK_TYPES = ("text", "input_text")


def text(value: object) -> str:
    return value if isinstance(value, str) else ""


def timestamp(value: object) -> float:
    """Normalize Unix seconds and ISO dates; unknown activity sorts last."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return 0.0


def plain_path(value: str) -> str:
    r"""Drop the `\\?\` long-path prefix, which folder checks accept but new processes don't.

    A process started in `\\?\D:\Project` silently runs in the Windows folder instead.
    """
    if value.startswith(LONG_UNC_PREFIX):
        return UNC_PREFIX + value.removeprefix(LONG_UNC_PREFIX)
    return value.removeprefix(LONG_PATH_PREFIX)


def modified_time(path: Path) -> float:
    """The activity fallback; a transcript deleted meanwhile just sorts last."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def sampled_records(path: Path) -> Iterator[dict[str, object]]:
    """Read complete records at both ends, never an entire large transcript."""
    for chunk in _samples(path):
        for line in chunk.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def _samples(path: Path) -> tuple[bytes, ...]:
    """The whole of a small file; of a large one, the complete lines at either end."""
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size <= SAMPLE_BYTES:
                return (stream.read(SAMPLE_BYTES),)
            head = stream.read(SAMPLE_BYTES).rpartition(b"\n")[0]
            # One byte earlier: if that byte ends a line, the tail starts with a whole record.
            stream.seek(max(SAMPLE_BYTES, size - SAMPLE_BYTES) - 1)
            tail = stream.read(SAMPLE_BYTES + 1).partition(b"\n")[2]
            return (head, tail)
    except OSError:
        return ()


def message_text(content: object) -> str:
    """Tool results and images are never conversation titles."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            text(block.get("text"))
            for block in content
            if isinstance(block, dict) and block.get("type") in TEXT_BLOCK_TYPES
        )
    return ""


def read_database(path: Path, query: str) -> list[sqlite3.Row]:
    """Respect the CLI's WAL and locks, without creating or migrating a database."""
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=SQLITE_TIMEOUT_SECONDS
    )
    try:
        connection.row_factory = sqlite3.Row
        return connection.execute(query).fetchall()
    finally:
        connection.close()
