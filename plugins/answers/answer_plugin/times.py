"""Times in other places: `zeit in bangalore`, `tokyo time`, `15:00 berlin in new york`.

Places are the cities from 100,000 inhabitants and the countries of GeoNames
(`places.tsv.gz`, built by `tools/build_places.py`), found by any of their names
without accents: Bangalore and Bengaluru, München and Munich. A real name beats
another place's alias, a country beats a city of the same name, and a larger city
a smaller one. Time zone abbreviations such as CET, PST or IST and offsets such as
UTC+5:30 work too. Everything is offline; the zones come from the IANA database.
"""

from __future__ import annotations

import gzip
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .text import Reply, fold, whole

PLACES_FILE = Path(__file__).with_name("places.tsv.gz")
# Abbreviations people write, to the zone that keeps its summer time right.
ZONE_ABBREVIATIONS = {
    "utc": "UTC", "gmt": "UTC",
    "cet": "Europe/Berlin", "cest": "Europe/Berlin", "mez": "Europe/Berlin",
    "mesz": "Europe/Berlin", "wet": "Europe/Lisbon", "eet": "Europe/Athens",
    "bst": "Europe/London", "msk": "Europe/Moscow",
    "est": "America/New_York", "edt": "America/New_York", "et": "America/New_York",
    "cst": "America/Chicago", "cdt": "America/Chicago", "ct": "America/Chicago",
    "mst": "America/Denver", "mdt": "America/Denver", "mt": "America/Denver",
    "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pt": "America/Los_Angeles",
    "ist": "Asia/Kolkata", "jst": "Asia/Tokyo", "kst": "Asia/Seoul", "hkt": "Asia/Hong_Kong",
    "sgt": "Asia/Singapore", "aest": "Australia/Sydney", "aedt": "Australia/Sydney",
}  # fmt: skip
# Names people type that GeoNames lacks, to the place's own name: countries in German,
# and short forms it drops as codes.
EXTRA_NAMES = {
    "Ägypten": "Egypt", "Argentinien": "Argentina", "Australien": "Australia",
    "Belgien": "Belgium", "Brasilien": "Brazil", "Bulgarien": "Bulgaria", "Dänemark": "Denmark",
    "Deutschland": "Germany", "Estland": "Estonia", "Finnland": "Finland",
    "Frankreich": "France", "Griechenland": "Greece", "Grossbritannien": "United Kingdom",
    "Indien": "India", "Indonesien": "Indonesia", "Irland": "Ireland", "Island": "Iceland",
    "Italien": "Italy", "Kanada": "Canada", "Kenia": "Kenya", "Kolumbien": "Colombia",
    "Kroatien": "Croatia", "Lettland": "Latvia", "Litauen": "Lithuania", "Marokko": "Morocco",
    "Mexiko": "Mexico", "Neuseeland": "New Zealand", "Niederlande": "Netherlands",
    "Norwegen": "Norway", "Österreich": "Austria", "Philippinen": "Philippines",
    "Polen": "Poland", "Rumänien": "Romania", "Russland": "Russia",
    "Saudi-Arabien": "Saudi Arabia", "Schweden": "Sweden", "Schweiz": "Switzerland",
    "Serbien": "Serbia", "Singapur": "Singapore", "Slowakei": "Slovakia",
    "Slowenien": "Slovenia", "Spanien": "Spain", "Südafrika": "South Africa",
    "Südkorea": "South Korea", "Thailand": "Thailand", "Tschechien": "Czechia",
    "Türkei": "Turkey", "Ukraine": "Ukraine", "Ungarn": "Hungary",
    "USA": "United States", "Vereinigte Staaten": "United States",
    "Vereinigtes Königreich": "United Kingdom", "Vereinigte Arabische Emirate": "United Arab Emirates",
    "China": "China", "Japan": "Japan", "Vietnam": "Vietnam", "Israel": "Israel",
    "Portugal": "Portugal", "Chile": "Chile", "Peru": "Peru",
    "US": "United States", "UK": "United Kingdom", "UAE": "United Arab Emirates",
    "LA": "Los Angeles", "NYC": "New York City", "NY": "New York City",
    "SF": "San Francisco", "DC": "Washington", "HK": "Hong Kong", "KL": "Kuala Lumpur",
}  # fmt: skip
_OFFSET = re.compile(r"(?:utc|gmt)\s*(?P<sign>[+-])\s*(?P<hours>\d{1,2})(?::?(?P<minutes>\d{2}))?")
_TIME_WORDS = r"(?:time|zeit|uhrzeit|now|jetzt)"
_NAME = r"[a-z][a-z0-9 .'+:-]*?[a-z0-9]|[a-z]"
_PLACE = rf"(?P<place>{_NAME})"
_TIME_IN = whole(rf"{_TIME_WORDS}\s+(?:in|at|im|in der|auf)?\s*{_PLACE}")
_PLACE_TIME = whole(rf"{_PLACE}\s+{_TIME_WORDS}")
_CLOCK = r"(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<suffix>am|pm|uhr|h)?"
_CONVERT = whole(rf"{_CLOCK}\s*(?P<source>{_NAME})?\s+(?:in|to|nach)\s+(?P<target>{_NAME})")


@dataclass(frozen=True, slots=True)
class Place:
    name: str  # As GeoNames writes it, such as Bengaluru.
    country: str  # The country's name; empty for a zone.
    zone: tzinfo

    @property
    def label(self) -> str:
        return f"{self.name}, {self.country}" if self.country else self.name


class Places:
    """Every place by its folded names; loaded once, on first use or in the background."""

    def __init__(self) -> None:
        self._index: dict[str, Place] | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._index is None:
                self._index = _index(_rows())

    def find(self, name: str) -> Place | None:
        """The place or time zone called `name`, already folded."""
        if (zone := _zone(name)) is not None:
            return zone
        self.load()
        return self._index.get(name)


@dataclass(frozen=True, slots=True)
class _Row:
    kind: str
    name: str
    country: str  # The country's name for a country, its code for a city.
    zone: str
    population: int
    aliases: tuple[str, ...]


def _rows() -> Iterator[_Row]:
    with PLACES_FILE.open("rb") as raw, gzip.open(raw, "rt", encoding="utf-8") as text:
        for line in text:
            kind, name, country, zone, population, aliases = line.rstrip("\n").split("\t")
            yield _Row(
                kind, name, country, zone, int(population), tuple(filter(None, aliases.split(";")))
            )


def _index(rows: Iterator[_Row]) -> dict[str, Place]:
    """Folded name to place. Own names come first, then `EXTRA_NAMES`, then aliases;
    within each, countries before cities and larger cities before smaller ones."""
    rows = list(rows)
    country_names = {row.country: row.name for row in rows if row.kind == "country"}
    ranked = sorted(rows, key=lambda row: (row.kind != "country", -row.population))
    places = [(row, _place(row, country_names)) for row in ranked]
    usable = [(row, place) for row, place in places if place is not None]
    index: dict[str, Place] = {}
    for row, place in usable:
        index.setdefault(fold(row.name), place)
    for extra, name in EXTRA_NAMES.items():
        if (place := index.get(fold(name))) is not None:
            index.setdefault(fold(extra), place)
    for row, place in usable:
        for alias in row.aliases:
            index.setdefault(fold(alias), place)
    return index


def _place(row: _Row, country_names: dict[str, str]) -> Place | None:
    """The row as a place; None for a zone this time zone database lacks."""
    try:
        zone = ZoneInfo(row.zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    country = "" if row.kind == "country" else country_names.get(row.country, row.country)
    return Place(row.name, country, zone)


def _zone(name: str) -> Place | None:
    """A time zone abbreviation or a UTC offset as a place."""
    if name in ZONE_ABBREVIATIONS:
        return Place(name.upper(), "", ZoneInfo(ZONE_ABBREVIATIONS[name]))
    match = _OFFSET.fullmatch(name)
    if match is None:
        return None
    sign = -1 if match["sign"] == "-" else 1
    offset = timedelta(hours=int(match["hours"]), minutes=int(match["minutes"] or 0))
    if offset > timedelta(hours=14):
        return None
    return Place(f"UTC{match['sign']}{_hours(offset)}", "", timezone(sign * offset))


def time_answer(text: str, now: datetime, places: Places) -> Reply | None:
    """The time somewhere now, or a time of day in another place; None otherwise.

    `now` is aware, in the user's own time zone.
    """
    folded = fold(text)
    for pattern in (_TIME_IN, _PLACE_TIME):
        match = pattern.fullmatch(folded)
        if match and (place := places.find(match["place"])) is not None:
            there = now.astimezone(place.zone)
            return Reply(there.strftime("%H:%M"), _detail(there, now, place))
    return _converted(text, folded, now, places)


def _converted(text: str, folded: str, now: datetime, places: Places) -> Reply | None:
    match = _CONVERT.fullmatch(folded)
    if match is None:
        return None
    clock = _clock(match["hour"], match["minute"], match["suffix"])
    target = places.find(match["target"])
    source = places.find(match["source"]) if match["source"] else None
    if clock is None or target is None or (match["source"] and source is None):
        return None
    if source is None and match["suffix"] is None and match["minute"] is None:
        return None  # `5 in tokyo` is no time; `5 uhr in tokyo` and `5:00 in tokyo` are.
    origin_zone = source.zone if source else now.tzinfo
    start = datetime.combine(now.astimezone(origin_zone).date(), clock, origin_zone)
    there = start.astimezone(target.zone)
    origin = source.label if source else "here"
    detail = f"{_detail(there, start, target)} · {start.strftime('%H:%M')} {origin}"
    return Reply(there.strftime("%H:%M"), detail)


def _clock(hour: str, minute: str | None, suffix: str | None) -> time | None:
    hours, minutes = int(hour), int(minute or 0)
    if suffix in ("am", "pm"):
        if not 1 <= hours <= 12:
            return None
        hours = hours % 12 + (12 if suffix == "pm" else 0)
    if hours > 23 or minutes > 59:
        return None
    return time(hours, minutes)


def _detail(there: datetime, here: datetime, place: Place) -> str:
    """Weekday, place, its UTC offset and how far it is ahead of the user."""
    offset = there.utcoffset() or timedelta()
    difference = offset - (here.utcoffset() or timedelta())
    if difference:
        sign = "+" if difference > timedelta() else "−"
        ahead = f" · {sign}{_hours(abs(difference))} h"
    else:
        ahead = " · same time"
    utc_offset = f"UTC{'−' if offset < timedelta() else '+'}{_hours(abs(offset))}"
    if place.label.replace("-", "−") == utc_offset:  # Asked for an offset: say it once.
        return f"{there.strftime('%A')} · {utc_offset}{ahead}"
    return f"{there.strftime('%A')} · {place.label} · {utc_offset}{ahead}"


def _hours(span: timedelta) -> str:
    minutes = int(span.total_seconds()) // 60
    hours, rest = divmod(minutes, 60)
    return f"{hours}:{rest:02d}" if rest else str(hours)
