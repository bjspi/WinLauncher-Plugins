"""Answers above the results: units, currencies, dates and times elsewhere; all offline.

The plugin is loaded the way WinLauncher loads it; its modules come from there.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from winlauncher.plugins.api import Answer, PluginContext
from winlauncher.plugins.registry import discover_plugins

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
FOUND = discover_plugins([PLUGINS])
PLUGIN = next(plugin for plugin in FOUND.plugins if plugin.id == "answers")
package_name = sys.modules[type(PLUGIN).__module__]._implementation.__name__
application = importlib.import_module(package_name + ".application")
currency = importlib.import_module(package_name + ".currency")
ExchangeRates, convert_currency = currency.ExchangeRates, currency.convert_currency
parse_ecb_rates, read_rates, write_rates = (
    currency.parse_ecb_rates,
    currency.read_rates,
    currency.write_rates,
)
date_answer = importlib.import_module(package_name + ".dates").date_answer
number_text = importlib.import_module(package_name + ".text").number_text
times = importlib.import_module(package_name + ".times")
Places, time_answer = times.Places, times.time_answer
convert_units = importlib.import_module(package_name + ".units").convert_units

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 7, 15, 0, tzinfo=BERLIN)  # A Saturday, winter time.
TODAY = NOW.date()
RATES = ExchangeRates(date(2026, 11, 6), {"USD": 1.1, "GBP": 0.85, "INR": 92.0})
PLACES = Places()
ECB_FILE = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube><Cube time="2026-11-06">
    <Cube currency="USD" rate="1.1165"/><Cube currency="JPY" rate="171.2"/>
  </Cube></Cube>
</gesmes:Envelope>"""


def shown(answer) -> tuple[str, str] | None:
    return None if answer is None else (answer.result, answer.detail)


class UnitTest(unittest.TestCase):
    def test_conversions_in_either_language_and_style(self):
        for text, expected in (
            ("5 km in mi", ("3.10686 mi", "5 km")),
            ("1,5 GB in MB", ("1500 MB", "1,5 GB")),
            ("100 °F in C", ("37.7778 °C", "100 °F")),
            ("0 celsius to fahrenheit", ("32 °F", "0 °C")),
            ("3 Tassen in ml", ("709.765 ml", "3 cup")),
            ("5 in in cm", ("12.7 cm", "5 in")),
            ("2 Stunden in min", ("120 min", "2 h")),
            ("1 kib in b", ("1024 B", "1 KiB")),
        ):
            with self.subTest(text=text):
                self.assertEqual(shown(convert_units(text)), expected)

    def test_anything_else_stays_a_search(self):
        for text in ("5 km", "5 km run", "5 km in kg", "5 km in km", "report", "km in mi"):
            with self.subTest(text=text):
                self.assertIsNone(convert_units(text))

    def test_numbers_keep_six_significant_digits(self):
        self.assertEqual(number_text(1234567.0, False), "1234567")
        self.assertEqual(number_text(0.000123456789, True), "0,000123457")
        self.assertEqual(number_text(2.0, False), "2")


class CurrencyTest(unittest.TestCase):
    def test_codes_names_and_symbols_before_or_after_the_amount(self):
        for text, expected in (
            ("100 usd in eur", "90.91 EUR"),
            ("50 € nach $", "55.00 USD"),
            ("20 Pfund in Euro", "23.53 EUR"),
            ("$100 to inr", "8363.64 INR"),
            ("1,5 euro in usd", "1,65 USD"),
        ):
            with self.subTest(text=text):
                self.assertEqual(convert_currency(text, RATES, TODAY).result, expected)

    def test_the_detail_names_the_rate_and_warns_when_it_is_old(self):
        detail = convert_currency("100 usd in eur", RATES, TODAY).detail
        self.assertEqual(detail, "100 USD · ECB rate of 2026-11-06")
        old = convert_currency("100 usd in eur", RATES, date(2026, 11, 20)).detail
        self.assertTrue(old.endswith("(offline)"))

    def test_without_rates_or_known_currencies_nothing_answers(self):
        for text in ("100 usd in eur", "100 abc in eur", "100 in eur", "usd 100 eur in usd"):
            with self.subTest(text=text):
                rates = None if text == "100 usd in eur" else RATES
                self.assertIsNone(convert_currency(text, rates, TODAY))

    def test_the_ecb_file_is_read_and_kept(self):
        rates = parse_ecb_rates(ECB_FILE)
        self.assertEqual(
            (rates.day, dict(rates.per_euro)), (date(2026, 11, 6), {"USD": 1.1165, "JPY": 171.2})
        )
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(read_rates(Path(folder)))
            write_rates(Path(folder), rates)
            self.assertEqual(read_rates(Path(folder)), rates)
        for broken in (b"<html>", b"<a/>", b"not xml"):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                parse_ecb_rates(broken)


class DateTest(unittest.TestCase):
    def test_arithmetic_and_countdowns_answer_in_the_asked_style(self):
        for text, expected in (
            ("heute + 3 wochen", ("28.11.2026", "Saturday, 28 November 2026 · in 21 days")),
            ("today + 1 month", ("2026-12-07", "Monday, 7 December 2026 · in 30 days")),
            ("2027-01-31 + 1 month", ("2027-02-28", "Sunday, 28 February 2027 · in 113 days")),
            ("gestern - 2 tage", ("04.11.2026", "Wednesday, 4 November 2026 · 3 days ago")),
            ("tage bis 24.12.", ("47 Tage", "Thursday, 24 December 2026")),
            ("days since 2026-01-01", ("310 days", "Thursday, 1 January 2026")),
            ("kw", ("KW 45", "02.11.2026 – 08.11.2026")),
            ("week 1 2027", ("Week 1", "2027-01-04 – 2027-01-10")),
        ):
            with self.subTest(text=text):
                self.assertEqual(shown(date_answer(text, TODAY)), expected)

    def test_dates_alone_and_words_stay_searches(self):
        for text in ("week", "2026-12-24", "24.12.", "heute", "kw 60", "31.02. + 1 tag"):
            with self.subTest(text=text):
                self.assertIsNone(date_answer(text, TODAY))


class TimeTest(unittest.TestCase):
    def test_times_in_places_by_any_of_their_names(self):
        for text, expected in (
            ("zeit in bangalore", ("19:30", "Saturday · Bengaluru, India · UTC+5:30 · +4:30 h")),
            ("time in Bengaluru", ("19:30", "Saturday · Bengaluru, India · UTC+5:30 · +4:30 h")),
            ("tokyo time", ("23:00", "Saturday · Tokyo, Japan · UTC+9 · +8 h")),
            ("uhrzeit in münchen", ("15:00", "Saturday · Munich, Germany · UTC+1 · same time")),
            ("zeit in indien", ("19:30", "Saturday · India · UTC+5:30 · +4:30 h")),
            ("zeit in monaco", ("15:00", "Saturday · Monaco · UTC+1 · same time")),
            ("time in la", ("06:00", "Saturday · Los Angeles, United States · UTC−8 · −9 h")),
            ("time in utc+5:30", ("19:30", "Saturday · UTC+5:30 · +4:30 h")),
        ):
            with self.subTest(text=text):
                self.assertEqual(shown(time_answer(text, NOW, PLACES)), expected)

    def test_a_time_of_day_converted_between_places(self):
        self.assertEqual(
            shown(time_answer("15:00 berlin in new york", NOW, PLACES)),
            (
                "09:00",
                "Saturday · New York City, United States · UTC−5 · −6 h · 15:00 Berlin, Germany",
            ),
        )
        self.assertEqual(time_answer("3pm pst to cet", NOW, PLACES).result, "00:00")
        self.assertEqual(time_answer("15 uhr in tokio", NOW, PLACES).result, "23:00")

    def test_unknown_places_and_bare_numbers_stay_searches(self):
        for text in ("zeit in rechnungen", "zeit tracking", "5 in tokyo", "25:00 in tokyo", "time"):
            with self.subTest(text=text):
                self.assertIsNone(time_answer(text, NOW, PLACES))


class PluginTest(unittest.TestCase):
    """The plugin as WinLauncher calls it: answers by option, rates by refresh."""

    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.plugin = application.AnswersPlugin()
        self.plugin.now = lambda: NOW
        self.plugin.places = PLACES
        patch.object(application, "fetch_rates", return_value=RATES).start()
        self.addCleanup(patch.stopall)

    def context(self, **options) -> PluginContext:
        defaults = {option.key: option.default for option in PLUGIN.options}
        return PluginContext(self.folder, {**defaults, **options}, log=logging.getLogger("t"))

    def test_the_host_loads_the_plugin_as_one_that_answers(self):
        self.assertEqual(FOUND.problems, [])
        self.assertTrue(PLUGIN.answers())
        self.assertEqual(FOUND.sources["answers"].version, "1.1.0")
        self.assertTrue(Path(PLUGIN.icon).is_file())

    def test_each_kind_answers_unless_switched_off(self):
        self.plugin.refresh(self.context())
        for text, option in (
            ("5 km in mi", "units"),
            ("100 usd in eur", "currencies"),
            ("kw", "dates"),
            ("time in tokyo", "times"),
        ):
            with self.subTest(text=text):
                self.assertIsInstance(self.plugin.answer(text, self.context()), Answer)
                self.assertIsNone(self.plugin.answer(text, self.context(**{option: False})))
        self.assertIsNone(self.plugin.answer("report", self.context()))

    def test_refresh_lists_nothing_and_fetches_old_rates_only(self):
        fetch = application.fetch_rates
        self.assertEqual(self.plugin.refresh(self.context()), [])
        self.assertEqual(read_rates(self.folder), RATES)
        self.plugin.refresh(self.context())  # Fresh: kept, not fetched again.
        self.assertEqual(fetch.call_count, 1)
        old = time.time() - application.RATES_MAX_AGE_S - 60
        os.utime(self.folder / currency.RATES_FILE, (old, old))
        self.plugin.refresh(self.context())
        self.assertEqual(fetch.call_count, 2)
        self.plugin.refresh(self.context(currencies=False))
        self.assertEqual(fetch.call_count, 2)

    def test_spaces_symbols_and_question_marks_are_forgiven(self):
        self.plugin.rates = RATES
        for text, expected in (
            ("1km in miles", "0.621371 mi"),
            ("1km in meilen", "0.621371 mi"),
            ("1 km in miles?", "0.621371 mi"),
            ("1km in mi.", "0.621371 mi"),
            ("5km->mi", "3.10686 mi"),
            ("5 km→mi", "3.10686 mi"),
            ("100usd  in  eur", "90.91 EUR"),
            ("100usd=eur", "90.91 EUR"),
            ("100 usd in eur?", "90.91 EUR"),
            ("tage bis 24.12.", "47 Tage"),
            ("zeit in tokio?", "23:00"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.plugin.answer(text, self.context()).result, expected)
        for text in ("100usdineur", "5kminmi"):  # Words need their spaces.
            with self.subTest(text=text):
                self.assertIsNone(self.plugin.answer(text, self.context()))

    def test_the_help_shows_examples_of_the_kinds_switched_on_and_they_answer(self):
        self.plugin.rates = RATES
        tips = self.plugin.tips(self.context())
        self.assertEqual(len(tips), sum(len(kind) for kind in application.TIPS.values()))
        for tip in tips:
            with self.subTest(example=tip.example):
                self.assertIsNotNone(self.plugin.answer(tip.example, self.context()))
        only_units = self.context(currencies=False, dates=False, times=False)
        self.assertEqual([tip.example for tip in self.plugin.tips(only_units)], ["5 km in mi"])

    def test_offline_keeps_the_rates_it_had(self):
        write_rates(self.folder, RATES)
        old = time.time() - application.RATES_MAX_AGE_S - 60
        os.utime(self.folder / currency.RATES_FILE, (old, old))
        application.fetch_rates.side_effect = OSError("offline")
        with self.assertLogs("t", "INFO"):
            self.plugin.refresh(self.context())
        self.assertEqual(self.plugin.answer("100 usd in eur", self.context()).result, "90.91 EUR")

    def test_rates_kept_by_an_earlier_run_answer_before_the_first_refresh(self):
        write_rates(self.folder, RATES)
        self.assertEqual(self.plugin.answer("100 usd in eur", self.context()).result, "90.91 EUR")


if __name__ == "__main__":
    unittest.main()
