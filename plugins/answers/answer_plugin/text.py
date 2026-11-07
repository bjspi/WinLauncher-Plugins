"""What every answer reads the same way: amounts, words in German or English, results.

Amounts take a decimal point or a decimal comma, and a result answers in the style
it was asked in, as the calculator does: `1,5 km in mi` gives `0,932057`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SIGNIFICANT_DIGITS = 6
# Between what is converted and what it becomes: words need spaces around them
# (`5 km in mi`), symbols do not (`5km->mi`, `100usd=aud`).
JOIN = r"(?:\s+(?:in|to|into|nach|zu|als|as)\s+|\s*(?:->|=|→)\s*)"
# Asking marks at the end are no part of the question: `1 km in miles?`.
_ASKING = " ?!"
AMOUNT = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"


@dataclass(frozen=True, slots=True)
class Reply:
    """What an answer shows: the result Enter copies, and a muted detail beside it."""

    result: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Amount:
    value: float
    decimal_comma: bool  # Typed with a decimal comma: answer with one.


def amount(text: str) -> Amount:
    """`1,5`, `1.5` or `,5`; raises ValueError for anything else."""
    return Amount(float(text.replace(",", ".")), "," in text)


def number_text(value: float, decimal_comma: bool) -> str:
    """At most six significant digits, without trailing zeros or an exponent where avoidable."""
    if value == 0:
        return "0"
    text = format(value, f".{SIGNIFICANT_DIGITS}g")
    if "e" in text and 1e-4 <= abs(value) < 1e15:
        text = f"{value:.{SIGNIFICANT_DIGITS}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if decimal_comma else text


def question(text: str) -> str:
    """`text` without what ends a question, such as `?`; a final dot may be a date's."""
    return text.rstrip(_ASKING)


def fold(text: str) -> str:
    """Casefolded, without accents and with single spaces: `München` is `munchen`."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.replace("ß", "ss").split())


def whole(pattern: str) -> re.Pattern[str]:
    """`pattern` matching a whole folded query, ignoring case."""
    return re.compile(rf"\s*{pattern}\s*", re.IGNORECASE)
