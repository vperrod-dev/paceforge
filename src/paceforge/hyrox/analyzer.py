"""HYROX race analysis engine — benchmarks, priorities, progression."""

from __future__ import annotations

from paceforge.hyrox.models import (
    HYROX_SPLIT_NAMES,
    RUNNING_SPLITS,
    STATION_SPLITS,
    HyroxRaceResult,
)

# ── Field benchmarks from 12,500-athlete analysis (season 7/8) ──────
# Source: imterence/hyrox_analysis ANALYSIS_SUMMARY.md
# These are mean times in seconds for the general HYROX field.

FIELD_AVG: dict[str, float] = {
    "Running_1": 318.0,   # ~5:18
    "Running_2": 330.0,   # ~5:30
    "Running_3": 342.0,   # ~5:42
    "Running_4": 348.0,   # ~5:48
    "Running_5": 354.0,   # ~5:54
    "Running_6": 360.0,   # ~6:00
    "Running_7": 366.0,   # ~6:06
    "Running_8": 378.0,   # ~6:18
    "SkiErg_1000m": 264.0,
    "Sled_Push_50m": 180.0,
    "Sled_Pull_50m": 226.6,
    "Burpee_Broad_Jump_80m": 225.3,
    "Row_1000m": 252.0,
    "Farmers_Carry_200m": 150.0,
    "Sandbag_Lunges_100m": 229.9,
    "Wall_Balls": 286.6,
    "Roxzone_Time": 298.5,
}

TOP3_AVG: dict[str, float] = {
    "Running_1": 290.5,
    "Running_2": 282.2,
    "Running_3": 289.0,
    "Running_4": 293.0,
    "Running_5": 295.0,
    "Running_6": 301.0,
    "Running_7": 307.0,
    "Running_8": 319.0,
    "SkiErg_1000m": 231.3,
    "Sled_Push_50m": 132.4,
    "Sled_Pull_50m": 140.3,
    "Burpee_Broad_Jump_80m": 140.7,
    "Row_1000m": 219.5,
    "Farmers_Carry_200m": 130.0,
    "Sandbag_Lunges_100m": 155.7,
    "Wall_Balls": 204.3,
    "Roxzone_Time": 203.3,
}

# Station display labels for UI
SPLIT_DISPLAY_NAMES: dict[str, str] = {
    "Running_1": "Run 1",
    "Running_2": "Run 2",
    "Running_3": "Run 3",
    "Running_4": "Run 4",
    "Running_5": "Run 5",
    "Running_6": "Run 6",
    "Running_7": "Run 7",
    "Running_8": "Run 8",
    "SkiErg_1000m": "SkiErg",
    "Sled_Push_50m": "Sled Push",
    "Sled_Pull_50m": "Sled Pull",
    "Burpee_Broad_Jump_80m": "Burpee Broad Jump",
    "Row_1000m": "Row",
    "Farmers_Carry_200m": "Farmers Carry",
    "Sandbag_Lunges_100m": "Sandbag Lunges",
    "Wall_Balls": "Wall Balls",
    "Roxzone_Time": "Roxzone",
}


def _splits_dict(result: HyroxRaceResult) -> dict[str, float | None]:
    """Convert splits list to {name: seconds} dict."""
    return {s.name: s.time_seconds for s in result.splits}


def _splits_rank(result: HyroxRaceResult) -> dict[str, tuple[int, int]]:
    """Map split name -> (rank, field_size) for splits that carry per-segment ranks."""
    out: dict[str, tuple[int, int]] = {}
    for s in result.splits:
        if s.rank and s.field_size:
            out[s.name] = (int(s.rank), int(s.field_size))
    return out


def _percentile(rank: int, field_size: int) -> int:
    """Percentile rank — 99 = best in field, higher is better."""
    return round(100 * (field_size - rank) / field_size) if field_size else 0


def _fmt_time(secs: float | None) -> str:
    if secs is None:
        return "—"
    total = int(secs)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cohort_benchmarks(result: HyroxRaceResult, gender: str = "M") -> dict:
    """Benchmarks adjusted to the race's own division/age-group (lazy import —
    benchmarks.py imports our base tables)."""
    from paceforge.hyrox.benchmarks import get_benchmarks

    return get_benchmarks(gender=gender, division=result.division,
                          age_group=result.age_group)


def analyze_race(result: HyroxRaceResult, gender: str = "M") -> dict:
    """Analyze a single race result — running fade, time breakdown, comparisons.

    Benchmarks are cohort-adjusted (gender/division/age-group) so "vs field"
    means the athlete's OWN field, not the Men/Open average.
    """
    bench = _cohort_benchmarks(result, gender)
    field_bench, top3_bench = bench["field_avg"], bench["top3_avg"]
    sd = _splits_dict(result)

    # Running analysis
    run_times = [sd.get(r) for r in RUNNING_SPLITS]
    valid_runs = [t for t in run_times if t is not None]
    total_running = sum(valid_runs) if valid_runs else 0

    # Station analysis
    station_times = [sd.get(s) for s in STATION_SPLITS]
    valid_stations = [t for t in station_times if t is not None]
    total_stations = sum(valid_stations) if valid_stations else 0

    # Roxzone
    roxzone = sd.get("Roxzone_Time", 0) or 0

    # Total
    total = result.total_time_seconds or (total_running + total_stations + roxzone)

    # Running fade %
    fade_pct = 0.0
    if len(valid_runs) >= 2 and valid_runs[0] and valid_runs[0] > 0:
        fade_pct = round(((valid_runs[-1] - valid_runs[0]) / valid_runs[0]) * 100, 1)

    # Compromised running classification based on actual splits
    if fade_pct < 8:
        running_class = "Strong Compromised Runner"
    elif fade_pct < 15:
        running_class = "Moderate Drop-off"
    else:
        running_class = "Severe Fade"

    # Running stats
    avg_run = round(sum(valid_runs) / len(valid_runs), 1) if valid_runs else 0
    avg_run_pace_display = _fmt_time(avg_run) + "/km" if avg_run else "—"

    # Time breakdown percentages
    running_pct = round((total_running / total) * 100, 1) if total > 0 else 0
    station_pct = round((total_stations / total) * 100, 1) if total > 0 else 0
    roxzone_pct = round((roxzone / total) * 100, 1) if total > 0 else 0

    # Per-split comparison to benchmarks (+ live per-segment rank/percentile when imported)
    ranks = _splits_rank(result)
    split_analysis = []
    for split_name in RUNNING_SPLITS + STATION_SPLITS:
        athlete_time = sd.get(split_name)
        field_avg = field_bench.get(split_name)
        top3_avg = top3_bench.get(split_name)
        if athlete_time is not None and field_avg:
            gap_field = round(athlete_time - field_avg, 1)
            gap_top3 = round(athlete_time - top3_avg, 1) if top3_avg else None
            rank, field_size = ranks.get(split_name, (0, 0))
            split_analysis.append({
                "name": split_name,
                "display": SPLIT_DISPLAY_NAMES.get(split_name, split_name),
                "athlete_seconds": athlete_time,
                "athlete_display": _fmt_time(athlete_time),
                "field_avg": field_avg,
                "field_avg_display": _fmt_time(field_avg),
                "top3_avg": top3_avg,
                "top3_avg_display": _fmt_time(top3_avg) if top3_avg else "—",
                "gap_vs_field": gap_field,
                "gap_vs_top3": gap_top3,
                "beats_field": gap_field < 0,
                "beats_top3": (gap_top3 is not None and gap_top3 < 0),
                "rank": rank or None,
                "field_size": field_size or None,
                "percentile": _percentile(rank, field_size) if rank and field_size else None,
                "is_run": split_name in RUNNING_SPLITS,
            })

    return {
        "total_time": total,
        "total_time_display": _fmt_time(total),
        "total_running": total_running,
        "total_running_display": _fmt_time(total_running),
        "total_stations": total_stations,
        "total_stations_display": _fmt_time(total_stations),
        "roxzone": roxzone,
        "roxzone_display": _fmt_time(roxzone),
        "running_pct": running_pct,
        "station_pct": station_pct,
        "roxzone_pct": roxzone_pct,
        "avg_run_seconds": avg_run,
        "avg_run_pace_display": avg_run_pace_display,
        "fade_pct": fade_pct,
        "running_class": running_class,
        "run_splits": [
            {"name": f"Run {i+1}", "seconds": run_times[i], "display": _fmt_time(run_times[i])}
            for i in range(len(run_times))
        ],
        "split_analysis": split_analysis,
        "segments": _ordered_segments(result),
        "benchmark_source": bench["source"],
        "benchmark_cohort": bench["cohort"],
    }


def _ordered_segments(result: HyroxRaceResult) -> list[dict]:
    """Every segment in race order with cumulative time + rank/percentile.

    Powers the cumulative pacing curve and the per-station rank chart.
    """
    sd = _splits_dict(result)
    ranks = _splits_rank(result)
    segments = []
    cumulative = 0.0
    for name in HYROX_SPLIT_NAMES:
        if name == "Roxzone_Time":
            continue
        secs = sd.get(name)
        if secs is None:
            continue
        cumulative += secs
        rank, field_size = ranks.get(name, (0, 0))
        segments.append({
            "name": name,
            "display": SPLIT_DISPLAY_NAMES.get(name, name),
            "seconds": secs,
            "display_time": _fmt_time(secs),
            "cumulative": round(cumulative, 1),
            "rank": rank or None,
            "field_size": field_size or None,
            "percentile": _percentile(rank, field_size) if rank and field_size else None,
            "is_run": name in RUNNING_SPLITS,
        })
    return segments


def compute_training_priorities(result: HyroxRaceResult, gender: str = "M") -> list[dict]:
    """Rank stations by improvement potential (gap vs cohort top-3 average)."""
    bench = _cohort_benchmarks(result, gender)
    sd = _splits_dict(result)
    priorities = []

    for split_name in RUNNING_SPLITS + STATION_SPLITS:
        athlete_time = sd.get(split_name)
        top3_avg = bench["top3_avg"].get(split_name)
        field_avg = bench["field_avg"].get(split_name)

        if athlete_time is None or top3_avg is None:
            continue

        gap_seconds = round(athlete_time - top3_avg, 1)
        gap_pct = round((gap_seconds / top3_avg) * 100, 1) if top3_avg > 0 else 0

        # Priority score: weighted combination of gap % and absolute gap
        priority_score = round(abs(gap_pct) * 0.6 + abs(gap_seconds) * 0.1, 1)

        priorities.append({
            "name": split_name,
            "display": SPLIT_DISPLAY_NAMES.get(split_name, split_name),
            "athlete_seconds": athlete_time,
            "athlete_display": _fmt_time(athlete_time),
            "top3_avg": top3_avg,
            "top3_avg_display": _fmt_time(top3_avg),
            "field_avg": field_avg,
            "gap_seconds": gap_seconds,
            "gap_pct": gap_pct,
            "priority_score": priority_score,
            "is_running": split_name in RUNNING_SPLITS,
        })

    # Sort by priority score descending (biggest gaps first)
    priorities.sort(key=lambda x: x["priority_score"], reverse=True)

    # Add rank + train_priority flags: >60s over the cohort benchmark, or one of
    # the two weakest stations — the "biggest marginal gains" rule of thumb.
    weakest_stations = [p["name"] for p in priorities if not p["is_running"]][:2]
    for i, p in enumerate(priorities):
        p["rank"] = i + 1
        p["train_priority"] = bool(
            (not p["is_running"] and p["gap_seconds"] > 60)
            or p["name"] in weakest_stations
        )

    return priorities


def compute_race_progression(results: list[HyroxRaceResult]) -> dict:
    """Compute progression trends across multiple races."""
    if not results:
        return {"races": [], "total_trend": [], "fade_trend": [], "improving": False}

    # Sort races chronologically by event_date
    def _sort_key(r: HyroxRaceResult) -> str:
        ed = r.event_date or ""
        # If already YYYY-MM-DD format, use directly
        if len(ed) >= 10 and ed[4] == "-":
            return ed
        # Try to extract year from "City YYYY" format
        import re
        m = re.search(r'\d{4}', ed)
        return m.group() if m else "0000"

    sorted_results = sorted(results, key=_sort_key)

    race_entries = []
    for i, r in enumerate(sorted_results):
        analysis = analyze_race(r)
        race_entries.append({
            "index": i + 1,
            "city": r.city,
            "event_date": r.event_date or r.city,
            "division": r.division,
            "total_seconds": r.total_time_seconds,
            "total_display": r.total_time_display or _fmt_time(r.total_time_seconds),
            "fade_pct": analysis["fade_pct"],
            "running_pct": analysis["running_pct"],
            "running_class": analysis["running_class"],
            "rank": r.rank,
        })

    # Total time trend
    total_trend = [e["total_seconds"] for e in race_entries if e["total_seconds"]]

    # Fade trend
    fade_trend = [e["fade_pct"] for e in race_entries]

    # Determine if improving (last few races faster than earlier)
    improving = False
    if len(total_trend) >= 3:
        first_half = sum(total_trend[:len(total_trend)//2]) / max(len(total_trend)//2, 1)
        second_half = sum(total_trend[len(total_trend)//2:]) / max(len(total_trend) - len(total_trend)//2, 1)
        improving = second_half < first_half

    # Best race
    valid_races = [e for e in race_entries if e["total_seconds"]]
    best = min(valid_races, key=lambda e: e["total_seconds"]) if valid_races else None

    # Per-station best times across all races
    station_bests: dict[str, float] = {}
    for r in sorted_results:
        for s in r.splits:
            if s.time_seconds and s.time_seconds > 0:
                if s.name not in station_bests or s.time_seconds < station_bests[s.name]:
                    station_bests[s.name] = s.time_seconds

    # Station-by-station comparison across races
    all_split_names = list(RUNNING_SPLITS) + list(STATION_SPLITS) + ["Roxzone_Time"]
    station_comparison: list[dict] = []
    for split_name in all_split_names:
        display = SPLIT_DISPLAY_NAMES.get(split_name, split_name)
        times_per_race = []
        for i, r in enumerate(sorted_results):
            sd = {s.name: s.time_seconds for s in r.splits}
            t = sd.get(split_name)
            times_per_race.append({
                "race_index": i + 1,
                "event": race_entries[i]["event_date"] if i < len(race_entries) else "",
                "seconds": t,
                "display": _fmt_time(t),
            })
        valid_times = [t["seconds"] for t in times_per_race if t["seconds"]]
        if not valid_times:
            continue
        # Compute improvement (first race vs last race with data)
        first_val = next((t["seconds"] for t in times_per_race if t["seconds"]), None)
        last_val = next((t["seconds"] for t in reversed(times_per_race) if t["seconds"]), None)
        improvement_seconds = None
        if first_val and last_val and len(valid_times) >= 2:
            improvement_seconds = first_val - last_val  # positive = improved
        station_comparison.append({
            "name": split_name,
            "display": display,
            "is_running": split_name.startswith("Running"),
            "times": times_per_race,
            "best_seconds": min(valid_times),
            "best_display": _fmt_time(min(valid_times)),
            "improvement_seconds": improvement_seconds,
        })

    return {
        "races": race_entries,
        "total_trend": total_trend,
        "fade_trend": fade_trend,
        "improving": improving,
        "best_race": best,
        "num_races": len(sorted_results),
        "station_bests": {
            k: {"seconds": v, "display": _fmt_time(v)}
            for k, v in station_bests.items()
        },
        "station_comparison": station_comparison,
    }
