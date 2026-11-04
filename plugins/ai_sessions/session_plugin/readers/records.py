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


def sampled_records(path: Path) -> Iterator[dict[str, object]]:
    """Read complete records at both ends, never an entire large transcript."""
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            head = stream.read(SAMPLE_BYTES)
            if size > SAMPLE_BYTES:
                head = head.rsplit(b"\n", 1)[0]
            chunks = [head]
            if size > SAMPLE_BYTES:
                offset = max(SAMPLE_BYTES, size - SAMPLE_BYTES)
                stream.seek(offset - 1)
                tail = stream.read(SAMPLE_BYTES + 1)
                chunks.append(tail.split(b"\n", 1)[-1])
    except OSError:
        return
    for chunk in chunks:
        for line in chunk.splitlines():
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(record, dict):
                yield record


def message_text(content: object) -> str:
    """Tool results and images are never conversation titles."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            text(block.get("text"))
            for block in content
            if isinstance(block, dict) and block.get("type") in ("text", "input_text")
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
