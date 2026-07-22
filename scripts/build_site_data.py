"""Precompute the derived JSON the static web UI reads.

The site is static (GitHub Pages), so anything the old FastAPI backend computed on
request must be baked into files at build time:

    data/analytics.json       — engine analytics over the stored profile
    data/hyrox_analysis.json  — per-race HYROX breakdown vs field benchmarks

Run from the repo root (CI does this in the Pages workflow before deploying):

    python scripts/build_site_data.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from paceforge import actions, store
from paceforge.hyrox.analyzer import (
    analyze_race,
    compute_compromise_by_station,
    compute_pacing_strategy_effectiveness,
    compute_race_progression,
    compute_training_priorities,
    predict_next_race,
)
from paceforge.hyrox.models import HyroxRaceResult

DATA = Path("data")


def _write(name: str, payload: object) -> None:
    (DATA / name).write_text(json.dumps(payload, indent=2, default=str))
    print(f"  wrote data/{name}")


def _race_id(r: HyroxRaceResult) -> str:
    """Stable per-race slug for detail routing + coach narrative filenames."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{r.event_date}-{r.city}".lower()).strip("-")
    return slug or "race"


def _build_hyrox() -> dict:
    hyrox = json.loads((DATA / "hyrox.json").read_text())
    gender = hyrox.get("search_gender") or "M"
    results = [HyroxRaceResult.model_validate(r) for r in hyrox.get("results", [])]
    races = []
    for r in results:
        races.append({
            "id": _race_id(r),
            "city": r.city,
            "event_date": r.event_date,
            "division": r.division,
            "rank": r.rank,
            "rank_age_group": r.rank_age_group,
            "field_size": r.field_size,
            "age_group": r.age_group,
            "total_display": r.total_time_display,
            **analyze_race(r, gender=gender),
        })
    latest = max(results, key=lambda r: r.event_date or "", default=None)
    return {
        "races": races,
        "priorities": compute_training_priorities(latest, gender=gender) if latest else [],
        "progression": compute_race_progression(results),
        "prediction": predict_next_race(results, gender=gender),
        "compromise_by_station": compute_compromise_by_station(results, gender=gender),
        "pacing_strategy": compute_pacing_strategy_effectiveness(results, gender=gender),
    }


def main() -> int:
    # A brand-new instance has no profile until its first Garmin sync lands; there
    # is nothing to derive yet, and failing here would mask the real reason.
    if store.load_profile() is None:
        print("no profile yet — nothing to publish")
        return 0
    _write("analytics.json", actions.analyze())
    _write("fitness.json", actions.fitness())

    hyrox_payload = _build_hyrox()
    _write("hyrox_analysis.json", hyrox_payload)

    # Placeholder so the UI's weekly view fetch never 404s. Claude writes a real
    # one (with a populated `content`) into data/weekly.json when reviewing a week.
    if not (DATA / "weekly.json").exists():
        _write("weekly.json", {"content": None})

    print(f"done — {len(hyrox_payload['races'])} hyrox races analysed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
