"""WinLauncher adapter: the options, the answer to typed text, and fresh exchange rates.

The plugin lists no items. Its refresh keeps the European Central Bank's rates of
the day in the plugin's data folder and loads the places in the background; its
answer reads only those, so it stays quick on every pause in typing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from winlauncher.plugins.api import Answer, Plugin, PluginContext, PluginItem, PluginOption

from .currency import (
    RATES_FILE,
    ExchangeRates,
    convert_currency,
    fetch_rates,
    read_rates,
    write_rates,
)
from .dates import date_answer
from .text import Reply, question
from .times import Places, time_answer
from .units import convert_units

ASSETS = Path(__file__).resolve().parent.parent / "assets"
UNITS_OPTION = "units"
CURRENCIES_OPTION = "currencies"
DATES_OPTION = "dates"
TIMES_OPTION = "times"
RATES_MAX_AGE_S = 12 * 60 * 60  # The ECB publishes once per working day.


class AnswersPlugin(Plugin):
    """Answers units, currencies, dates and times elsewhere in the calculator's row."""

    id = "answers"
    label = "Answer"
    description = (
        "Converts units and currencies, counts dates and tells the time elsewhere, in the "
        "row above the results: 5 km in mi, 100 usd in eur, heute + 3 wochen, zeit in bangalore."
    )
    icon = str(ASSETS / "answers.svg")
    refresh_minutes = 360  # Fetches only when the kept rates are older than a day's half.
    options = (
        PluginOption(UNITS_OPTION, "Units", True, "5 km in mi, 100 °F in C, 1,5 GB in MB."),
        PluginOption(
            CURRENCIES_OPTION,
            "Currencies",
            True,
            "100 usd in eur, with the European Central Bank's rates, fetched once a day.",
        ),
        PluginOption(DATES_OPTION, "Dates", True, "heute + 3 wochen, days until 24.12., kw 45."),
        PluginOption(
            TIMES_OPTION, "Times elsewhere", True, "zeit in Bangalore, 15:00 Berlin in New York."
        ),
    )

    def __init__(self) -> None:
        self.places = Places()
        self.rates: ExchangeRates | None = None  # Replaced whole, so answers may read it.
        self.now: Callable[[], datetime] = lambda: datetime.now().astimezone()

    def refresh(self, context: PluginContext) -> list[PluginItem]:
        """Lists nothing: keeps the exchange rates of the day and loads the places."""
        if context.options[CURRENCIES_OPTION]:
            self.rates = _fresh_rates(context)
        if context.options[TIMES_OPTION]:
            self.places.load()
        return []

    def answer(self, text: str, context: PluginContext) -> Answer | None:
        reply = self._reply(text, context)
        return Answer(reply.result, reply.detail) if reply is not None else None

    def _reply(self, text: str, context: PluginContext) -> Reply | None:
        """The first kind that understands the whole text: currencies, units, dates, times."""
        options = context.options
        now = self.now()
        text = question(text)
        if options[CURRENCIES_OPTION]:
            if self.rates is None:  # Before the first refresh: what an earlier run kept.
                self.rates = read_rates(context.data_dir)
            if found := convert_currency(text, self.rates, now.date()):
                return found
        if options[UNITS_OPTION] and (found := convert_units(text)):
            return found
        if options[DATES_OPTION] and (found := date_answer(text, now.date())):
            return found
        if options[TIMES_OPTION]:
            return time_answer(text, now, self.places)
        return None


def _fresh_rates(context: PluginContext) -> ExchangeRates | None:
    """The kept rates, fetched anew once they are old; offline keeps the old ones."""
    kept = read_rates(context.data_dir)
    if kept is not None and not _is_old(context.data_dir / RATES_FILE):
        return kept
    try:
        rates = fetch_rates()
        write_rates(context.data_dir, rates)
    except (OSError, ValueError) as exc:
        context.log.info("Exchange rates not updated, keeping those of %s: %s", _day(kept), exc)
        return kept
    context.log.info("Exchange rates of %s fetched", rates.day)
    return rates


def _is_old(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime >= RATES_MAX_AGE_S
    except OSError:
        return True


def _day(rates: ExchangeRates | None) -> str:
    return str(rates.day) if rates is not None else "no day"
