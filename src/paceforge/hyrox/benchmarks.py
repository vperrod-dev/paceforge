"""Division/gender/age-aware HYROX benchmarks.

Base tables are the season 7/8 12,500-athlete Men/Open means (see analyzer.py).
Other cohorts are derived with documented factors because public per-division
split tables are patchy — every result carries a ``source`` tag so a consumer
can tell measured baseline from scaled approximation, and the factors can be
replaced with real tables as they become available.

Factor provenance:
- Women/Open: average women's finish ≈ 1:54 vs men's ≈ 1:40 (hyroxdatalab.com
  benchmarks) → ~+13% on runs; station implements are lighter for women so the
  station gap is smaller (~+8%).
- Pro division: heavier implements slow stations (~+8%) but the field is far
  fitter (runs ~-10% vs open average).
- Age: finish times slow roughly 2-3 min per decade after 35 on a ~100 min race
  (hyroxdatalab age-group analysis) → ~+2.5% per decade past the 35-39 band.
"""

from __future__ import annotations

import re

from paceforge.hyrox.analyzer import FIELD_AVG, TOP3_AVG

_WOMEN_RUN_FACTOR = 1.13
_WOMEN_STATION_FACTOR = 1.08
_PRO_RUN_FACTOR = 0.90
_PRO_STATION_FACTOR = 1.08
_AGE_FACTOR_PER_DECADE = 0.025
_AGE_REFERENCE = 35  # the base tables skew to the huge 25-39 open cohort

_RUN_KEYS = {k for k in FIELD_AVG if k.startswith("Running_")} | {"Roxzone_Time"}


def _age_decades(age_group: str | None) -> int:
    """Whole decades past the reference band, from a group like '40-44'.

    30s → 0, 40s → 1, 50s → 2, …
    """
    if not age_group:
        return 0
    m = re.match(r"(\d{2})", str(age_group))
    if not m:
        return 0
    return max(0, (int(m.group(1)) - (_AGE_REFERENCE - 5)) // 10)


def get_benchmarks(gender: str = "M", division: str = "",
                   age_group: str | None = None) -> dict:
    """Benchmark tables adjusted for the athlete's cohort.

    Returns ``{"field_avg": {...}, "top3_avg": {...}, "source": str,
    "cohort": str}`` in the same split-name keys as analyzer.FIELD_AVG.
    """
    run_f = station_f = 1.0
    tags = ["men_open_s7s8"]
    if str(gender).upper().startswith(("F", "W")):
        run_f *= _WOMEN_RUN_FACTOR
        station_f *= _WOMEN_STATION_FACTOR
        tags.append("scaled_women")
    if "pro" in str(division).lower():
        run_f *= _PRO_RUN_FACTOR
        station_f *= _PRO_STATION_FACTOR
        tags.append("scaled_pro")
    decades = _age_decades(age_group)
    if decades:
        age_f = 1 + _AGE_FACTOR_PER_DECADE * decades
        run_f *= age_f
        station_f *= age_f
        tags.append(f"age_adjusted_{age_group}")

    def _scale(table: dict[str, float]) -> dict[str, float]:
        return {k: round(v * (run_f if k in _RUN_KEYS else station_f), 1)
                for k, v in table.items()}

    cohort_bits = ["W" if str(gender).upper().startswith(("F", "W")) else "M",
                   "Pro" if "pro" in str(division).lower() else "Open"]
    if age_group:
        cohort_bits.append(str(age_group))
    return {
        "field_avg": _scale(FIELD_AVG),
        "top3_avg": _scale(TOP3_AVG),
        "source": "+".join(tags),
        "cohort": " ".join(cohort_bits),
    }
