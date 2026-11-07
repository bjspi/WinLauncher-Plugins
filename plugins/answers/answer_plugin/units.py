"""Unit conversions: `5 km in mi`, `100 °F in C`, `1,5 GB in MB`, `3 Tassen in ml`.

Units are named in German or English, singular, plural or as symbols. Only a
complete `<amount> <unit> <in|to|nach…> <unit>` of one kind of quantity is an
answer, so a search such as `5 km run` stays a search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .text import AMOUNT, JOIN, Reply, amount, fold, number_text, whole


class Quantity(StrEnum):
    LENGTH = "length"
    MASS = "mass"
    VOLUME = "volume"
    AREA = "area"
    SPEED = "speed"
    TEMPERATURE = "temperature"
    DATA = "data"
    DURATION = "duration"


@dataclass(frozen=True, slots=True)
class Unit:
    symbol: str  # Shown in the result.
    quantity: Quantity
    factor: float  # Of the quantity's base unit: metre, kilogram, litre, m², m/s, byte, second.
    offset: float = 0.0  # Temperatures: base (kelvin) = value * factor + offset.
    names: tuple[str, ...] = ()  # Further spellings, folded.


_UNITS = (
    Unit(
        "mm",
        Quantity.LENGTH,
        0.001,
        names=("millimeter", "millimetre", "millimeters", "millimetres"),
    ),
    Unit(
        "cm",
        Quantity.LENGTH,
        0.01,
        names=("zentimeter", "centimeter", "centimetre", "centimeters", "centimetres"),
    ),
    Unit("m", Quantity.LENGTH, 1, names=("meter", "metre", "meters", "metres", "metern")),
    Unit(
        "km",
        Quantity.LENGTH,
        1000,
        names=("kilometer", "kilometre", "kilometers", "kilometres", "kilometern"),
    ),
    Unit("in", Quantity.LENGTH, 0.0254, names=("inch", "inches", "zoll", '"')),
    Unit("ft", Quantity.LENGTH, 0.3048, names=("foot", "feet", "fuss")),
    Unit("yd", Quantity.LENGTH, 0.9144, names=("yard", "yards")),
    Unit("mi", Quantity.LENGTH, 1609.344, names=("mile", "miles", "meile", "meilen")),
    Unit("nmi", Quantity.LENGTH, 1852, names=("seemeile", "seemeilen", "sm")),
    Unit("mg", Quantity.MASS, 1e-6, names=("milligram", "milligramm", "milligrams")),
    Unit("g", Quantity.MASS, 0.001, names=("gram", "gramm", "grams", "gramme")),
    Unit("kg", Quantity.MASS, 1, names=("kilo", "kilos", "kilogram", "kilogramm", "kilograms")),
    Unit("t", Quantity.MASS, 1000, names=("tonne", "tonnes", "tonnen")),
    Unit("lb", Quantity.MASS, 0.45359237, names=("lbs", "pound", "pounds", "pfund")),
    Unit("oz", Quantity.MASS, 0.028349523125, names=("ounce", "ounces", "unze", "unzen")),
    Unit("st", Quantity.MASS, 6.35029318, names=("stone", "stones")),
    Unit("ml", Quantity.VOLUME, 0.001, names=("milliliter", "millilitre", "milliliters")),
    Unit("cl", Quantity.VOLUME, 0.01, names=("zentiliter", "centiliter", "centilitre")),
    Unit("dl", Quantity.VOLUME, 0.1, names=("deziliter", "deciliter", "decilitre")),
    Unit("l", Quantity.VOLUME, 1, names=("liter", "litre", "liters", "litres", "litern")),
    Unit("m³", Quantity.VOLUME, 1000, names=("m3", "kubikmeter", "cubic meter", "cubic metre")),
    Unit("gal", Quantity.VOLUME, 3.785411784, names=("gallon", "gallons", "gallone", "gallonen")),
    Unit("qt", Quantity.VOLUME, 0.946352946, names=("quart", "quarts")),
    Unit("pt", Quantity.VOLUME, 0.473176473, names=("pint", "pints")),
    Unit("cup", Quantity.VOLUME, 0.2365882365, names=("cups", "tasse", "tassen")),
    Unit("fl oz", Quantity.VOLUME, 0.0295735295625, names=("floz", "fluid ounce", "fluid ounces")),
    Unit("tbsp", Quantity.VOLUME, 0.015, names=("el", "essloffel", "tablespoon", "tablespoons")),
    Unit("tsp", Quantity.VOLUME, 0.005, names=("tl", "teeloffel", "teaspoon", "teaspoons")),
    Unit(
        "m²", Quantity.AREA, 1, names=("m2", "qm", "quadratmeter", "square meter", "square metre")
    ),
    Unit("km²", Quantity.AREA, 1e6, names=("km2", "quadratkilometer", "square kilometer")),
    Unit("ha", Quantity.AREA, 1e4, names=("hektar", "hectare", "hectares")),
    Unit("acre", Quantity.AREA, 4046.8564224, names=("acres",)),
    Unit("ft²", Quantity.AREA, 0.09290304, names=("ft2", "sqft", "square feet", "square foot")),
    Unit("km/h", Quantity.SPEED, 1 / 3.6, names=("kmh", "kph", "stundenkilometer")),
    Unit("mph", Quantity.SPEED, 0.44704, names=("miles per hour",)),
    Unit("m/s", Quantity.SPEED, 1, names=("meter pro sekunde", "meters per second")),
    Unit("kn", Quantity.SPEED, 1852 / 3600, names=("knot", "knots", "knoten")),
    Unit("°C", Quantity.TEMPERATURE, 1, 273.15, names=("c", "celsius", "grad", "grad celsius")),
    Unit("°F", Quantity.TEMPERATURE, 5 / 9, 273.15 - 32 * 5 / 9, names=("f", "fahrenheit")),
    Unit("K", Quantity.TEMPERATURE, 1, names=("k", "kelvin")),
    Unit("B", Quantity.DATA, 1, names=("b", "byte", "bytes")),
    Unit("kB", Quantity.DATA, 1e3, names=("kb", "kilobyte", "kilobytes")),
    Unit("MB", Quantity.DATA, 1e6, names=("mb", "megabyte", "megabytes")),
    Unit("GB", Quantity.DATA, 1e9, names=("gb", "gigabyte", "gigabytes")),
    Unit("TB", Quantity.DATA, 1e12, names=("tb", "terabyte", "terabytes")),
    Unit("KiB", Quantity.DATA, 2**10, names=("kib", "kibibyte")),
    Unit("MiB", Quantity.DATA, 2**20, names=("mib", "mebibyte")),
    Unit("GiB", Quantity.DATA, 2**30, names=("gib", "gibibyte")),
    Unit("TiB", Quantity.DATA, 2**40, names=("tib", "tebibyte")),
    Unit("s", Quantity.DURATION, 1, names=("sec", "second", "seconds", "sekunde", "sekunden")),
    Unit("min", Quantity.DURATION, 60, names=("minute", "minutes", "minuten", "mins")),
    Unit("h", Quantity.DURATION, 3600, names=("hour", "hours", "stunde", "stunden", "std")),
    Unit("d", Quantity.DURATION, 86400, names=("day", "days", "tag", "tage", "tagen")),
    Unit("wk", Quantity.DURATION, 604800, names=("week", "weeks", "woche", "wochen")),
)
# Every spelling, folded, to its unit; a symbol's own case is kept for kB and K.
UNITS = {fold(name): unit for unit in _UNITS for name in (unit.symbol, *unit.names)}
_UNIT_WORDS = "|".join(sorted((re.escape(name) for name in UNITS), key=len, reverse=True))
_CONVERSION = whole(
    rf"(?P<amount>{AMOUNT})\s*(?P<source>{_UNIT_WORDS}){JOIN}(?P<target>{_UNIT_WORDS})\.?"
)


def convert_units(text: str) -> Reply | None:
    """The conversion `text` asks for; None if it is no complete conversion."""
    match = _CONVERSION.fullmatch(fold(text))
    if match is None:
        return None
    source, target = UNITS[match["source"]], UNITS[match["target"]]
    if source.quantity != target.quantity or source is target:
        return None
    asked = amount(match["amount"])
    base = asked.value * source.factor + source.offset
    value = (base - target.offset) / target.factor
    shown = number_text(asked.value, asked.decimal_comma)
    result = f"{number_text(value, asked.decimal_comma)} {target.symbol}"
    return Reply(result, f"{shown} {source.symbol}")
