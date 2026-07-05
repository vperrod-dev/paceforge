"""HYROX race analysis engine — benchmarks, priorities, progression."""

from __future__ import annotations

import re

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


# Published pacing benchmarks (hyroxdatalab.com run-variance analysis): elites keep
# run1→run8 spread under ~15 s/km and deviate ≤~27 s from their average on the worst
# run; recreational athletes roughly double that. HYROX runs are 1 km, so seconds
# per split ≈ s/km directly.
_ELITE_RUN_SPREAD_S = 15.0
_TOO_FAST_START_S = 20.0
_ELITE_WORST_DEV_S = 27.5
_REC_WORST_DEV_S = 51.4


def _pacing_quality(valid_runs: list[float]) -> dict:
    """Grade the 8-run pacing (0-100) and flag the classic execution errors."""
    if len(valid_runs) < 4:
        return {"available": False}
    mean = sum(valid_runs) / len(valid_runs)
    spread = max(valid_runs) - min(valid_runs)
    fade = valid_runs[-1] - valid_runs[0]
    worst_dev = max(r - mean for r in valid_runs)
    slowest_idx = valid_runs.index(max(valid_runs)) + 1

    flags: list[str] = []
    if valid_runs[0] == min(valid_runs) and fade > _TOO_FAST_START_S:
        flags.append(
            f"Went out too fast — Run 1 was your fastest and you gave back "
            f"{fade:.0f}s by Run {len(valid_runs)}. Elites keep the spread under "
            f"{_ELITE_RUN_SPREAD_S:.0f}s."
        )
    if slowest_idx >= 7:
        flags.append(
            f"Late-race collapse — Run {slowest_idx} was your slowest. The slowest run "
            "should land mid-race (5-6); a run-7/8 low point means pacing or aerobic base."
        )
    if worst_dev > _REC_WORST_DEV_S:
        flags.append(
            f"Worst run drifted {worst_dev:.0f}s off your average — recreational-level "
            f"variance (elite ≈ {_ELITE_WORST_DEV_S:.0f}s). Even pacing is free speed."
        )
    if not flags and spread <= _ELITE_RUN_SPREAD_S:
        flags.append(f"Elite-level pacing — {spread:.0f}s spread across all runs. Protect this.")

    # 0-100: full marks at elite spread/deviation, linear penalty beyond.
    score = 100.0
    score -= max(0.0, spread - _ELITE_RUN_SPREAD_S) * 1.2
    score -= max(0.0, worst_dev - _ELITE_WORST_DEV_S) * 0.8
    return {
        "available": True,
        "score": round(max(0.0, min(100.0, score))),
        "spread_seconds": round(spread, 1),
        "fade_seconds": round(fade, 1),
        "worst_deviation_seconds": round(worst_dev, 1),
        "slowest_run": slowest_idx,
        "flags": flags,
    }


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

    pacing_quality = _pacing_quality(valid_runs)

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
        "segments": _ordered_segments(result, top3_bench),
        "pacing_quality": pacing_quality,
        "time_lost": _time_lost_waterfall(split_analysis, roxzone, field_bench, top3_bench),
        "roxzone_analysis": _roxzone_analysis(roxzone, total, field_bench),
        "benchmark_source": bench["source"],
        "benchmark_cohort": bench["cohort"],
    }


def _time_lost_waterfall(split_analysis: list[dict], roxzone: float,
                         field_bench: dict, top3_bench: dict) -> dict:
    """Seconds recoverable per segment vs the cohort — the "where are my minutes
    hiding" ranking. Only positive gaps count (a segment you already beat the
    benchmark on has nothing to recover)."""
    def _items(gap_key: str, rox_bench: float | None) -> dict:
        items = [
            {"name": s["name"], "display": s["display"], "seconds": s[gap_key],
             "is_run": s["is_run"]}
            for s in split_analysis
            if s.get(gap_key) is not None and s[gap_key] > 0
        ]
        if roxzone and rox_bench and roxzone - rox_bench > 0:
            items.append({"name": "Roxzone_Time", "display": "Roxzone",
                          "seconds": round(roxzone - rox_bench, 1), "is_run": False})
        items.sort(key=lambda i: i["seconds"], reverse=True)
        return {"total": round(sum(i["seconds"] for i in items), 1), "items": items}

    return {
        "vs_field": _items("gap_vs_field", field_bench.get("Roxzone_Time")),
        "vs_top3": _items("gap_vs_top3", top3_bench.get("Roxzone_Time")),
    }


# Roxzone benchmarks (hyroxdatalab.com roxzone-efficiency analysis): transitions are
# ~6.5% of race time on average; elites total 4-5 min across ~16 zone passes
# (~15 s each) while recreational athletes give away 3+ extra minutes.
_ROXZONE_PASSES = 16
_ELITE_ROXZONE_S = 270.0
_BENCH_ROXZONE_PCT = 6.5


def _roxzone_analysis(roxzone: float, total: float, field_bench: dict) -> dict:
    if not roxzone or not total:
        return {"available": False}
    field_rox = field_bench.get("Roxzone_Time")
    return {
        "available": True,
        "per_pass_seconds": round(roxzone / _ROXZONE_PASSES, 1),
        "pct_of_race": round(100 * roxzone / total, 1),
        "benchmark_pct": _BENCH_ROXZONE_PCT,
        "vs_field_seconds": round(roxzone - field_rox, 1) if field_rox else None,
        "vs_elite_seconds": round(roxzone - _ELITE_ROXZONE_S, 1),
        "recoverable_seconds": round(max(0.0, roxzone - _ELITE_ROXZONE_S), 1),
    }


def _ordered_segments(result: HyroxRaceResult, top3_bench: dict | None = None) -> list[dict]:
    """Every segment in race order with cumulative time + rank/percentile.

    Powers the cumulative pacing curve, the per-segment standing line, and the
    cumulative gap-to-top-3 curve (where in the race the gap actually opens).
    """
    sd = _splits_dict(result)
    ranks = _splits_rank(result)
    top3_bench = top3_bench or {}
    segments = []
    cumulative = 0.0
    cumulative_gap = 0.0
    for name in HYROX_SPLIT_NAMES:
        if name == "Roxzone_Time":
            continue
        secs = sd.get(name)
        if secs is None:
            continue
        cumulative += secs
        top3 = top3_bench.get(name)
        if top3:
            cumulative_gap += secs - top3
        rank, field_size = ranks.get(name, (0, 0))
        segments.append({
            "name": name,
            "display": SPLIT_DISPLAY_NAMES.get(name, name),
            "seconds": secs,
            "display_time": _fmt_time(secs),
            "cumulative": round(cumulative, 1),
            "cumulative_gap_top3": round(cumulative_gap, 1) if top3_bench else None,
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


def _race_sort_key(r: HyroxRaceResult) -> str:
    """Chronological sort key: 'YYYY-MM-DD' event_date, else a bare year pulled
    out of a 'City YYYY' string, else '0000' (undated races sort first)."""
    ed = r.event_date or ""
    if len(ed) >= 10 and ed[4] == "-":
        return ed
    m = re.search(r'\d{4}', ed)
    return m.group() if m else "0000"


def _sorted_by_date(results: list[HyroxRaceResult]) -> list[HyroxRaceResult]:
    return sorted(results, key=_race_sort_key)


def compute_race_progression(results: list[HyroxRaceResult]) -> dict:
    """Compute progression trends across multiple races."""
    if not results:
        return {"races": [], "total_trend": [], "fade_trend": [], "improving": False}

    sorted_results = _sorted_by_date(results)

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

    # Percentile trend — rank-derived, so it controls for field strength/course:
    # "am I getting more competitive?" rather than just "am I getting faster?".
    overall_pct = []
    for i, r in enumerate(sorted_results):
        try:
            rank, field = int(r.rank), int(r.field_size)
        except (TypeError, ValueError):
            continue
        if rank and field:
            overall_pct.append({
                "race_index": i + 1,
                "event": race_entries[i]["event_date"],
                "percentile": _percentile(rank, field),
            })
    station_pct: dict[str, list[dict]] = {}
    for i, r in enumerate(sorted_results):
        for name, (rank, field) in _splits_rank(r).items():
            station_pct.setdefault(name, []).append({
                "race_index": i + 1,
                "event": race_entries[i]["event_date"],
                "percentile": _percentile(rank, field),
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
        "percentile_trend": {"overall": overall_pct, "stations": station_pct},
    }


def predict_next_race(results: list[HyroxRaceResult], gender: str = "M") -> dict:
    """Project the athlete's next HYROX finish time from their own race history.

    With 2+ races: an ordinary-least-squares trend line over race index vs.
    total time, extrapolated one race forward and clamped to within the
    athlete's own observed range (a short series shouldn't be allowed to
    extrapolate to an implausible time). With exactly 1 race: that race's time,
    with no trend to fit. With 0: the field average for the athlete's gender
    from `hyrox.benchmarks` — a population estimate, not a personal one.
    """
    if not results:
        from paceforge.hyrox.benchmarks import get_benchmarks

        bench = get_benchmarks(gender=gender)
        total = sum(bench["field_avg"].values())
        return {
            "predicted_seconds": round(total, 1),
            "predicted_display": _fmt_time(total),
            "method": "cohort_field_average",
            "races_used": 0,
            "basis": "No race history yet — field average for your gender.",
        }

    totals = [r.total_time_seconds for r in _sorted_by_date(results) if r.total_time_seconds]
    if len(totals) < 2:
        latest = totals[-1] if totals else None
        return {
            "predicted_seconds": round(latest, 1) if latest else None,
            "predicted_display": _fmt_time(latest),
            "method": "latest_race",
            "races_used": len(totals),
            "basis": "Only one timed race on record — using it as the estimate.",
        }

    n = len(totals)
    xs = list(range(n))
    mean_x, mean_y = sum(xs) / n, sum(totals) / n
    variance = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, totals)) / variance
    intercept = mean_y - slope * mean_x
    predicted = intercept + slope * n  # one race past the last observed index

    lower, upper = min(totals) * 0.85, max(totals) * 1.3
    predicted = min(max(predicted, lower), upper)
    trend = "improving" if slope < -1 else ("slowing" if slope > 1 else "plateauing")

    return {
        "predicted_seconds": round(predicted, 1),
        "predicted_display": _fmt_time(predicted),
        "method": "trend",
        "races_used": n,
        "trend": trend,
        "seconds_per_race": round(slope, 1),
        "basis": f"Linear trend across your last {n} races.",
    }


def compute_pacing_strategy_effectiveness(results: list[HyroxRaceResult], gender: str = "M") -> dict:
    """Does even pacing actually pay off for THIS athlete, across their own career?

    The existing `_pacing_quality` grades a single race against elite/recreational
    benchmarks. This instead correlates the athlete's own fade % with their own
    field percentile, race over race (Pearson's r) — a personalized answer, since
    some athletes' results are decided by stations or roxzone, not running fade,
    and the generic elite benchmark can't tell them that.
    """
    points: list[tuple[float, int]] = []
    for r in results:
        try:
            rank, field = int(r.rank), int(r.field_size)
        except (TypeError, ValueError):
            continue
        if not rank or not field:
            continue
        fade = analyze_race(r, gender=gender).get("fade_pct")
        if fade is None:
            continue
        points.append((fade, _percentile(rank, field)))

    if len(points) < 3:
        return {"available": False, "races_used": len(points)}

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    n = len(points)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return {"available": False, "races_used": n}
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    correlation = covariance / (var_x * var_y) ** 0.5

    if correlation < -0.3:
        read = ("Your best races are the ones where you fade the least — pacing "
                "discipline is worth real placings for you.")
    elif correlation > 0.3:
        read = ("Counterintuitively, your better results come with MORE fade — you "
                "may be pacing too conservatively early and leaving speed on the table.")
    else:
        read = ("No clear link yet between running fade and result — other factors "
                "(stations, roxzone) are probably deciding more of your races.")

    return {
        "available": True,
        "races_used": n,
        "correlation": round(correlation, 2),
        "read": read,
    }


# Fixed HYROX station order: which station immediately precedes each run.
# Run 1 has no preceding station (it's the race-opening baseline).
_STATION_BEFORE_RUN: dict[int, str] = {
    2: "SkiErg_1000m",
    3: "Sled_Push_50m",
    4: "Sled_Pull_50m",
    5: "Burpee_Broad_Jump_80m",
    6: "Row_1000m",
    7: "Farmers_Carry_200m",
    8: "Sandbag_Lunges_100m",
}


def compute_compromise_by_station(results: list[HyroxRaceResult], gender: str = "M") -> dict:
    """Career-level: which station transition costs the most *extra* running
    fade, once the ordinary cumulative-fatigue curve is subtracted out.

    HYROX's station order is fixed, so "run N" and "the run right after
    station X" are the same partition — every athlete slows down through the
    race regardless of which station they just did. This isolates the
    station-specific cost by comparing the athlete's own fade-from-Run-1 % at
    each position against the field's average fade-from-Run-1 % at that same
    position (from `hyrox.benchmarks`); the field curve stands in for
    "expected" fatigue by race stage. A positive excess means that transition
    costs this athlete more than it costs the field; negative means they hold
    up better than average through it.
    """
    per_position: dict[int, list[float]] = {i: [] for i in _STATION_BEFORE_RUN}
    for r in results:
        bench = _cohort_benchmarks(r, gender)
        field = bench["field_avg"]
        sd = _splits_dict(r)
        run1, field_run1 = sd.get("Running_1"), field.get("Running_1")
        if not run1 or not field_run1:
            continue
        for i in _STATION_BEFORE_RUN:
            run_i, field_run_i = sd.get(f"Running_{i}"), field.get(f"Running_{i}")
            if run_i is None or field_run_i is None:
                continue
            athlete_pct = (run_i - run1) / run1 * 100
            field_pct = (field_run_i - field_run1) / field_run1 * 100
            per_position[i].append(athlete_pct - field_pct)

    stations = []
    for i, station in _STATION_BEFORE_RUN.items():
        vals = per_position[i]
        if not vals:
            continue
        stations.append({
            "run_position": i,
            "station": station,
            "station_display": SPLIT_DISPLAY_NAMES.get(station, station),
            "excess_fade_pct": round(sum(vals) / len(vals), 1),
            "races_used": len(vals),
        })
    stations.sort(key=lambda s: s["excess_fade_pct"], reverse=True)
    return {"available": bool(stations), "stations": stations}
