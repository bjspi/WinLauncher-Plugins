# Answers

Answers typed questions in the row above the results, where WinLauncher shows a
calculation: units, currencies, dates and the time elsewhere, in German or English.
<kbd>Enter</kbd> copies the result; the muted text beside it says what was converted,
from which day a rate is, or where a time applies. Needs WinLauncher 0.17 or newer.

```text
5 km in mi · 100 °F in C · 1,5 GB in MB     3.10686 mi · 37.7778 °C · 1500 MB
3 Tassen in ml · 2 Stunden in min           709.765 ml · 120 min
100 usd in eur · 50 € nach $ · £20 to inr   89.57 EUR   (ECB rate of the day)
heute + 3 wochen · today + 1 month          28.11.2026 · 2026-12-07
tage bis 24.12. · days since 2026-01-01     47 Tage · 310 days
kw · week 45                                KW 45: 02.11.2026 – 08.11.2026
zeit in bangalore · tokyo time              19:30, Bengaluru, India, +4:30 h
15:00 berlin in new york · 3pm pst to cet   09:00 · 00:00
```

Spaces are forgiving: `1km in miles`, `100usd  in aud`, `5km->mi` and `100usd=aud`
all work, and a closing `?` or `!` is ignored. Only the words between the two sides
(`in`, `to`, `nach`, …) need a space around them.

A text is answered only when all of it fits one of these shapes and its units,
currencies or places are known. `zeit tracking`, `5 km run` or a bare date stay
ordinary searches. Arithmetic, such as `200 + 10%`, is WinLauncher's own and needs
no plugin.

## Settings

Settings → Plugins → Answers has one switch per kind, all on: **Units**,
**Currencies**, **Dates** and **Times elsewhere**.

## How it reads what you type

- **Units:** `<amount> <unit> in|to|into|nach|zu|als|->|=|→ <unit>`, for length, mass,
  volume, area, speed, temperature, data and durations. Units go by symbol or name,
  singular or plural, German or English: `km`, `Kilometer`, `Zoll`, `inch`, `Pfund`,
  `Tassen`, `EL`, `°F`, `GiB`. Six significant digits; a decimal comma is answered
  with one.
- **Currencies:** the same shape with ISO codes, symbols (`€ $ £ ¥ ₹`) or names
  (`euro`, `dollar`, `pfund`, `franken`, `yen`, `rupien`, …), before or after the
  amount; two decimals.
- **Dates:** `<date> ± <n> <tage|wochen|monate|jahre>` (or in English),
  `tage bis|seit <date>`, `days until|since <date>`, `kw`, `kw 45`, `week 45 2027`.
  A date is heute/today, morgen/tomorrow, gestern/yesterday, `24.12.`, `24.12.2026`
  or `2026-12-24`. Asked in German or with a dotted date, the answer is `28.11.2026`,
  otherwise `2026-11-28`. One month after 31 January is the last day of February.
- **Times elsewhere:** `zeit|uhrzeit|time in <place>`, `<place> time`, and
  `<time> [<place>] in|to|nach <place>` with `15:00`, `15 uhr` or `3pm`. Places are
  about 6,300 cities from 100,000 inhabitants and every country, by any of their
  names without accents (München, Munich; Bangalore, Bengaluru; Indien, USA, LA),
  plus `CET`, `PST`, `IST` and the like and `UTC+5:30`. A real name beats another
  place's alias, a country a city of the same name, a larger city a smaller one.

## What it fetches

Only the exchange rates: the European Central Bank's
[reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html),
about 30 currencies against the euro, published once per working day. The plugin
fetches the small XML file when the kept one is older than 12 hours, checking every
6 hours, and keeps it as `exchange-rates.json` in its data folder. Offline, it keeps
answering with the last rates; after four days without new ones, the answer says
"(offline)". With **Currencies** off, nothing is fetched. Everything else works
without a network: places and time zones come with the plugin.

## Data

The places come from [GeoNames](https://www.geonames.org/) under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), reduced to cities from
100,000 inhabitants with their Latin-script names, and the countries in the time
zone of their capitals. `tools/build_places.py` builds
`plugins/answers/answer_plugin/places.tsv.gz` from GeoNames' `cities15000.zip` and
`countryInfo.txt`:

```powershell
python -I tools/build_places.py <folder>\cities15000.txt <folder>\countryInfo.txt
python -m unittest discover -s tests -p test_answers.py
```

Time zones come from Python's IANA database; on Windows the plugin installs the
`tzdata` package for it.
