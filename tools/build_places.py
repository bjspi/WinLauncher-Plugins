"""Build `plugins/answers/answer_plugin/places.tsv.gz` from GeoNames, for times in other places.

    python tools/build_places.py cities15000.txt countryInfo.txt

Both files come from https://download.geonames.org/export/dump/ (CC BY 4.0). The
result keeps cities from MIN_POPULATION inhabitants with their Latin-script names,
so Bangalore finds Bengaluru and München finds Munich, and every country with the
time zone of its capital. One line per place:

    kind <TAB> name <TAB> country <TAB> time zone <TAB> population <TAB> aliases (;)
"""

from __future__ import annotations

import argparse
import gzip
import re
from pathlib import Path

MIN_POPULATION = 100_000
MAX_ALIAS_LENGTH = 40
OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "answers"
    / "answer_plugin"
    / "places.tsv.gz"
)
# Names a person types: Latin letters with accents, spaces, dots, hyphens, apostrophes.
_TYPEABLE = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ .'-]*")
_CODE = re.compile(r"[A-Z0-9]{2,4}")  # Airport and other codes among the alternate names.


def city_rows(path: Path) -> list[tuple[str, str, str, int, list[str]]]:
    """Name, country code, time zone, population and aliases of every city in the file."""
    rows = []
    with path.open(encoding="utf-8", newline="") as file:
        for line in file:  # GeoNames quotes nothing: tabs only separate the fields.
            row = line.rstrip("\n").split("\t")
            name, ascii_name, alternates = row[1], row[2], row[3]
            country, population, zone = row[8], int(row[14] or 0), row[17]
            if not zone:
                continue
            rows.append((name, country, zone, population, _aliases(name, ascii_name, alternates)))
    return rows


def _aliases(name: str, ascii_name: str, alternates: str) -> list[str]:
    seen = {name.casefold()}
    aliases = []
    for alias in (ascii_name, *alternates.split(",")):
        alias = alias.strip()
        if (
            len(alias) > MAX_ALIAS_LENGTH
            or not _TYPEABLE.fullmatch(alias)
            or _CODE.fullmatch(alias)
            or alias.casefold() in seen
        ):
            continue
        seen.add(alias.casefold())
        aliases.append(alias)
    return aliases


def country_rows(path: Path, cities: list[tuple[str, str, str, int, list[str]]]) -> list[tuple]:
    """Each country named after GeoNames, in the time zone of its capital."""
    zones = {}
    for name, country, zone, _population, aliases in cities:
        for known in (name, *aliases):
            zones.setdefault((country, known.casefold()), zone)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        fields = line.split("\t")
        code, country_name, capital = fields[0], fields[4], fields[5]
        zone = zones.get((code, capital.casefold()))
        if zone:
            rows.append(("country", country_name, code, zone, 0, []))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cities", type=Path, help="cities15000.txt")
    parser.add_argument("countries", type=Path, help="countryInfo.txt")
    args = parser.parse_args()
    every_city = city_rows(args.cities)
    # Small capitals, such as Monaco's, still give their country its time zone.
    countries = country_rows(args.countries, every_city)
    cities = [city for city in every_city if city[3] >= MIN_POPULATION]
    rows = [("city", *city) for city in cities] + countries
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8", newline="\n") as out:
        for kind, name, country, zone, population, aliases in rows:
            out.write("\t".join((kind, name, country, zone, str(population), ";".join(aliases))))
            out.write("\n")
    print(f"{len(cities)} cities, {len(rows) - len(cities)} countries: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
