"""Date arithmetic: `heute + 3 wochen`, `days until 24.12.`, `kw 45`, `kw`.

A date is `today`, `tomorrow` and `yesterday` (also German), `24.12.`, `24.12.2026`
or `2026-12-24`. An answer asked in German, or with a German date, shows its date
as 28.11.2026; otherwise as 2026-11-28. Anything else stays a search, such as a
bare date, which finds files named after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .text import Reply, fold, whole

_GERMAN_WORDS = frozenset(
    {"heute", "morgen", "gestern", "tage", "tag", "wochen", "woche", "monate", "monat",
     "jahre", "jahr", "bis", "seit", "kw", "zwischen", "und"}
)  # fmt: skip
_DAY_WORDS = {
    "today": 0, "heute": 0, "now": 0, "jetzt": 0,
    "tomorrow": 1, "morgen": 1, "yesterday": -1, "gestern": -1,
}  # fmt: skip
_STEPS = {
    "d": "days", "day": "days", "days": "days", "tag": "days", "tage": "days", "tagen": "days",
    "w": "weeks", "wk": "weeks", "week": "weeks", "weeks": "weeks", "woche": "weeks",
    "wochen": "weeks", "month": "months", "months": "months", "monat": "months",
    "monate": "months", "monaten": "months", "y": "years", "year": "years", "years": "years",
    "jahr": "years", "jahre": "years", "jahren": "years",
}  # fmt: skip
_DATE = r"(?:today|heute|now|jetzt|tomorrow|morgen|yesterday|gestern|\d{1,2}\.\d{1,2}\.(?:\d{4})?|\d{4}-\d{2}-\d{2})"
_STEP = "|".join(sorted(_STEPS, key=len, reverse=True))
_ARITHMETIC = whole(
    rf"(?P<date>{_DATE})\s*(?P<sign>[+-])\s*(?P<count>\d{{1,5}})\s*(?P<step>{_STEP})"
)
_UNTIL = whole(rf"(?:days|tage)\s+(?P<direction>until|till|to|bis|since|seit)\s+(?P<date>{_DATE})")
_WEEK = whole(r"(?:kw|calendar week|week|woche)(?:\s+(?P<week>\d{1,2})(?:\s+(?P<year>\d{4}))?)?")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Style:
    german: bool

    def short(self, day: date) -> str:
        return day.strftime("%d.%m.%Y") if self.german else day.isoformat()


def date_answer(text: str, today: date) -> Reply | None:
    """The date or number of days `text` asks for; None for anything else."""
    folded = fold(text)
    style = _Style(bool(_GERMAN_WORDS & set(re.split(r"[\s+-]+", folded))) or "." in folded)
    for answer in (_arithmetic, _until, _week):
        result = answer(folded, today, style)
        if result is not None:
            return Reply(*result)
    return None


def _arithmetic(text: str, today: date, style: _Style) -> tuple[str, str] | None:
    match = _ARITHMETIC.fullmatch(text)
    start = _date(match["date"], today) if match else None
    if start is None:
        return None
    count = int(match["count"]) * (1 if match["sign"] == "+" else -1)
    shifted = _shifted(start, _STEPS[match["step"]], count)
    if shifted is None:
        return None
    return style.short(shifted), f"{_long(shifted)} · {_distance(today, shifted)}"


def _until(text: str, today: date, style: _Style) -> tuple[str, str] | None:
    match = _UNTIL.fullmatch(text)
    day = _date(match["date"], today) if match else None
    if day is None:
        return None
    if match["direction"] in ("since", "seit"):
        days = (today - day).days
    else:
        days = (day - today).days
    unit = "Tage" if style.german else "days"
    return f"{days} {unit}", _long(day)


def _week(text: str, today: date, style: _Style) -> tuple[str, str] | None:
    match = _WEEK.fullmatch(text)
    if match is None or (match["week"] is None and text.strip() in ("week", "woche")):
        return None  # `week` alone is a word to search for; `kw` is not.
    year = int(match["year"] or today.isocalendar().year)
    number = int(match["week"] or today.isocalendar().week)
    try:
        monday = date.fromisocalendar(year, number, 1)
    except ValueError:
        return None
    sunday = monday + timedelta(days=6)
    label = "KW" if style.german else "Week"
    return f"{label} {number}", f"{style.short(monday)} – {style.short(sunday)}"


def _date(text: str, today: date) -> date | None:
    """A typed date; `24.12.` is in the current year."""
    if text in _DAY_WORDS:
        return today + timedelta(days=_DAY_WORDS[text])
    try:
        if "-" in text:
            return date.fromisoformat(text)
        day, month, year = (text.split(".") + [""])[:3]
        return date(int(year) if year else today.year, int(month), int(day))
    except ValueError:
        return None


def _shifted(start: date, step: str, count: int) -> date | None:
    """`start` moved by whole steps; a month later than 31 January is 28 or 29 February."""
    try:
        if step == "days":
            return start + timedelta(days=count)
        if step == "weeks":
            return start + timedelta(weeks=count)
        months = start.month - 1 + count * (12 if step == "years" else 1)
        year, month = start.year + months // 12, months % 12 + 1
        return date(year, month, min(start.day, _days_in(year, month)))
    except (ValueError, OverflowError):
        return None


def _days_in(year: int, month: int) -> int:
    following = date(year + month // 12, month % 12 + 1, 1)
    return (following - timedelta(days=1)).day


def _long(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]} {day.year}"


def _distance(today: date, day: date) -> str:
    days = (day - today).days
    if days == 0:
        return "today"
    return f"in {days} days" if days > 0 else f"{-days} days ago"
