"""Currency conversions with the European Central Bank's daily reference rates.

`100 usd in eur`, `50 € nach $`, `20 Pfund in Euro`. The ECB publishes about 30
rates against the euro once per working day, around 16:00 CET; WinLauncher keeps
the last ones in its data folder, so conversions work offline and say from when
their rate is. No account and no key: one small XML file.
"""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .text import AMOUNT, JOIN, Reply, amount, fold, number_text, whole

ECB_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FETCH_TIMEOUT_S = 10
MAX_RATES_BYTES = 64 * 1024  # The file is about 2 KB; anything larger is not it.
RATES_FILE = "exchange-rates.json"
EURO = "EUR"
_ECB_NAMESPACE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"
# Names and symbols people type, folded, besides the three-letter codes.
CURRENCY_NAMES = {
    "€": "EUR", "euro": "EUR", "euros": "EUR",
    "$": "USD", "dollar": "USD", "dollars": "USD", "us-dollar": "USD", "us dollar": "USD",
    "£": "GBP", "pfund": "GBP", "pound": "GBP", "pounds": "GBP", "pfund sterling": "GBP",
    "¥": "JPY", "yen": "JPY",
    "franken": "CHF", "franc": "CHF", "francs": "CHF", "fr.": "CHF",
    "yuan": "CNY", "renminbi": "CNY",
    "₹": "INR", "rupee": "INR", "rupees": "INR", "rupie": "INR", "rupien": "INR",
    "zloty": "PLN", "forint": "HUF", "lira": "TRY", "won": "KRW", "rand": "ZAR",
    "kanadische dollar": "CAD", "canadian dollar": "CAD", "australische dollar": "AUD",
    "australian dollar": "AUD", "schwedische kronen": "SEK", "norwegische kronen": "NOK",
    "danische kronen": "DKK",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class ExchangeRates:
    """Units of each currency one euro buys, as published on `day`."""

    day: date
    per_euro: Mapping[str, float] = field(default_factory=dict)

    def rate(self, code: str) -> float | None:
        return 1.0 if code == EURO else self.per_euro.get(code)


def _currency_pattern() -> str:
    names = sorted((re.escape(name) for name in CURRENCY_NAMES), key=len, reverse=True)
    return rf"(?:[a-z]{{3}}|{'|'.join(names)})"


_CURRENCY = _currency_pattern()
_CONVERSION = whole(
    rf"(?:(?P<before>{_CURRENCY})\s*)?(?P<amount>{AMOUNT})\s*(?P<after>{_CURRENCY})?"
    rf"{JOIN}(?P<target>{_CURRENCY})\.?"
)


def convert_currency(text: str, rates: ExchangeRates | None, today: date) -> Reply | None:
    """The conversion `text` asks for at `rates`; None without rates or a known currency."""
    if rates is None:
        return None
    match = _CONVERSION.fullmatch(fold(text))
    if match is None or (match["before"] is None) == (match["after"] is None):
        return None
    source = _code(match["before"] or match["after"], rates)
    target = _code(match["target"], rates)
    if source is None or target is None or source == target:
        return None
    asked = amount(match["amount"])
    value = asked.value / rates.rate(source) * rates.rate(target)
    result = f"{_money(value, asked.decimal_comma)} {target}"
    detail = f"{number_text(asked.value, asked.decimal_comma)} {source} · ECB rate of {rates.day}"
    if (today - rates.day).days > 4:  # Weekends and holidays have no new rate.
        detail += " (offline)"
    return Reply(result, detail)


def _code(word: str, rates: ExchangeRates) -> str | None:
    code = CURRENCY_NAMES.get(word, word.upper())
    return code if rates.rate(code) is not None else None


def _money(value: float, decimal_comma: bool) -> str:
    """Two decimals, as prices are written; more for amounts below one cent."""
    text = f"{value:.2f}" if abs(value) >= 0.01 or value == 0 else number_text(value, False)
    return text.replace(".", ",") if decimal_comma else text


# Fetching and keeping them -------------------------------------------------------


def parse_ecb_rates(xml: bytes) -> ExchangeRates:
    """The ECB's daily file; raises ValueError for anything else."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"The ECB rates are unreadable: {exc}") from exc
    day = root.find(f".//{_ECB_NAMESPACE}Cube[@time]")
    if day is None:
        raise ValueError("The ECB file names no day.")
    rates = {
        cube.get("currency", ""): float(cube.get("rate", "nan"))
        for cube in day.findall(f"{_ECB_NAMESPACE}Cube")
    }
    usable = {code: rate for code, rate in rates.items() if len(code) == 3 and rate > 0}
    if not usable:
        raise ValueError("The ECB file holds no rates.")
    return ExchangeRates(date.fromisoformat(day.get("time", "")), usable)


def fetch_rates() -> ExchangeRates:
    """Today's rates from the ECB; raises OSError or ValueError. Runs on a worker."""
    request = urllib.request.Request(ECB_RATES_URL, headers={"User-Agent": "WinLauncher"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:  # noqa: S310
        return parse_ecb_rates(response.read(MAX_RATES_BYTES))


def read_rates(folder: Path) -> ExchangeRates | None:
    """The rates kept last time; None before the first fetch or after damage."""
    try:
        saved = json.loads((folder / RATES_FILE).read_text(encoding="utf-8"))
        rates = {str(code): float(rate) for code, rate in saved["per_euro"].items()}
        return ExchangeRates(date.fromisoformat(saved["day"]), rates)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def write_rates(folder: Path, rates: ExchangeRates) -> None:
    """Replace atomically; raises OSError."""
    path = folder / RATES_FILE
    temporary = path.with_suffix(".tmp")
    saved = {"day": rates.day.isoformat(), "per_euro": dict(rates.per_euro)}
    temporary.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    temporary.replace(path)
