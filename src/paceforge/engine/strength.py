"""Strength, power, and HYROX-specific assessment for a hybrid athlete.

HONESTY RULE: HR and duration from a strength_training session cannot measure
strength. Any HR-derived figure here is tagged confidence="low" with an explicit
note so the UI never presents an HR proxy as if it were a real strength number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from paceforge.hyrox.models import RUNNING_SPLITS, STATION_SPLITS

# Rough division medians (seconds) for "HYROX Men / Open" — researched ballpark
# values, used only to map a station time to an approximate percentile.
STATION_MEDIANS = {
    "SkiErg_1000m": 232.0,
    "Sled_Push_50m": 172.0,
    "Sled_Pull_50m": 281.0,
    "Burpee_Broad_Jump_80m": 315.0,
    "Row_1000m": 230.0,
    "Farmers_Carry_200m": 110.0,
    "Sandbag_Lunges_100m": 300.0,
    "Wall_Balls": 388.0,
}

# Window for "recent" anaerobic stimulus.
_ANAEROBIC_WINDOW_DAYS = 28
# Garmin anaerobic Training Effect at/above this counts as a real anaerobic hit.
_ANAEROBIC_TE_THRESHOLD = 3.0

_HR_PROXY_NOTE = "HR-only proxy, not a strength measure"


@dataclass
class StrengthHyroxReport:
    """Container for all strength/HYROX metrics; serialized via to_dict()."""

    station_percentiles: dict
    compromised_run_race: dict
    transition_cost: dict
    anaerobic_capacity: dict
    strength_endurance: dict
    hybrid_balance: dict
    data_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "station_percentiles": self.station_percentiles,
            "compromised_run_race": self.compromised_run_race,
            "transition_cost": self.transition_cost,
            "anaerobic_capacity": self.anaerobic_capacity,
            "strength_endurance": self.strength_endurance,
            "hybrid_balance": self.hybrid_balance,
            "data_gaps": self.data_gaps,
        }


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _splits_dict(result: dict) -> dict[str, float | None]:
    """Flatten a result's splits list into {name: time_seconds}."""
    return {s["name"]: s.get("time_seconds") for s in result.get("splits", [])}


def _latest_result(hyrox_results: list) -> dict | None:
    """Most recent race by event_date string; falls back to last in list."""
    if not hyrox_results:
        return None
    return max(hyrox_results, key=lambda r: r.get("event_date", ""))


def _bench(benchmarks: dict | None, key: str):
    """Safe getter — any missing key is treated as None."""
    if not benchmarks:
        return None
    return benchmarks.get(key)


def compute_station_percentiles(hyrox_results: list, gender: str = "M") -> dict:
    """Map each station time to an approximate percentile vs cohort medians.

    Faster-than-median -> higher percentile. Percentile is a ratio scaled around
    50: a time equal to the median lands at 50, twice as fast approaches 100.
    Medians come from the shared cohort benchmarks (gender/division/age-aware),
    falling back to the researched Men/Open ballparks.
    """
    result = _latest_result(hyrox_results)
    if result is None:
        return {"available": False}

    from paceforge.hyrox.benchmarks import get_benchmarks

    bench = get_benchmarks(gender=gender, division=result.get("division", ""),
                           age_group=result.get("age_group"))
    medians = {name: bench["field_avg"].get(name) or STATION_MEDIANS[name]
               for name in STATION_SPLITS}

    splits = _splits_dict(result)
    stations = {}
    for name in STATION_SPLITS:
        time_sec = splits.get(name)
        median = medians[name]
        if time_sec is None:
            continue
        # ratio>1 means faster than median -> above the 50th percentile.
        percentile = _clamp(50.0 * (median / time_sec))
        stations[name] = {
            "time": time_sec,
            "median": median,
            "percentile": round(percentile, 1),
        }

    # Rank by percentile descending; weakest = lowest percentile.
    ranked = sorted(stations.items(), key=lambda kv: kv[1]["percentile"], reverse=True)
    for rank, (name, _) in enumerate(ranked, start=1):
        stations[name]["rank"] = rank
    weakest_3 = [name for name, _ in ranked[-3:][::-1]]

    return {"available": True, "stations": stations, "weakest_3": weakest_3}


def compute_compromised_run_race(hyrox_results: list) -> dict:
    """RunFade%: how much the back-half runs slow down vs the opening runs.

    Caveat: Running_1 and Running_8 are roughly half-distance in HYROX, so they
    bias the means; we flag this rather than rescale.
    """
    result = _latest_result(hyrox_results)
    if result is None:
        return {"available": False}

    splits = _splits_dict(result)
    run_times = {name: splits.get(name) for name in RUNNING_SPLITS}

    opening = [splits.get("Running_1"), splits.get("Running_2")]
    closing = [splits.get(f"Running_{i}") for i in range(5, 9)]
    opening = [t for t in opening if t is not None]
    closing = [t for t in closing if t is not None]
    if not opening or not closing:
        return {"available": False}

    mean_open = sum(opening) / len(opening)
    mean_close = sum(closing) / len(closing)
    fade_pct = (mean_close - mean_open) / mean_open * 100.0

    if fade_pct < 8:
        grade = "elite"
    elif fade_pct < 15:
        grade = "solid"
    elif fade_pct < 25:
        grade = "gap"
    else:
        grade = "limiter"

    return {
        "available": True,
        "fade_pct": round(fade_pct, 1),
        "run_times": run_times,
        "grade": grade,
        "caveat": "Running_1 and Running_8 are ~half distance; means are biased by this.",
    }


def compute_transition_cost(hyrox_results: list) -> dict:
    """Surface total Roxzone (transition) time and grade it."""
    result = _latest_result(hyrox_results)
    if result is None:
        return {"available": False}

    roxzone = _splits_dict(result).get("Roxzone_Time")
    if roxzone is None:
        return {"available": False}

    if roxzone < 300:
        grade = "good"
    elif roxzone <= 480:
        grade = "average"
    else:
        grade = "bleeding"

    return {"available": True, "roxzone_sec": roxzone, "grade": grade}


def compute_anaerobic_capacity(activities: list) -> dict:
    """Count recent high-anaerobic-TE sessions as a stimulus signal."""
    cutoff = datetime.now() - timedelta(days=_ANAEROBIC_WINDOW_DAYS)
    tes = []
    for act in activities:
        start = getattr(act, "start_time", None)
        if start is None or start < cutoff:
            continue
        te = getattr(act, "training_effect_anaerobic", None)
        if te is not None and te >= _ANAEROBIC_TE_THRESHOLD:
            tes.append(te)

    count = len(tes)
    mean_te = round(sum(tes) / count, 2) if count else 0.0
    if count == 0:
        signal = "under-stimulated"
    elif count <= 3:
        signal = "adequate"
    else:
        signal = "high"

    return {
        "anaerobic_te_sessions_28d": count,
        "mean_anaerobic_te": mean_te,
        "signal": signal,
        "cp_w_prime_note": "CP / W' modeling needs power data — see running module if power available.",
    }


def _grade_high_good(value: float, strong: float, weak: float) -> str:
    """Higher is better (reps)."""
    if value >= strong:
        return "strong"
    if value <= weak:
        return "weak"
    return "moderate"


def _grade_low_good(value: float, strong: float, weak: float) -> str:
    """Lower is better (times)."""
    if value <= strong:
        return "strong"
    if value >= weak:
        return "weak"
    return "moderate"


def compute_strength_endurance(benchmarks: dict | None, activities: list) -> dict:
    """Grade strength-endurance from user benchmarks; HR proxy if none exist."""
    assessments = {}
    gaps = []

    wall_balls = _bench(benchmarks, "wall_balls_max")
    if wall_balls is not None:
        assessments["wall_balls_max"] = {
            "value": wall_balls,
            "grade": _grade_high_good(wall_balls, strong=50, weak=25),
        }
    else:
        gaps.append("no wall_balls_max benchmark")

    lunges = _bench(benchmarks, "sandbag_lunges_max")
    if lunges is not None:
        assessments["sandbag_lunges_max"] = {
            "value": lunges,
            "grade": _grade_high_good(lunges, strong=40, weak=20),
        }
    else:
        gaps.append("no sandbag_lunges_max benchmark")

    reps_60s = _bench(benchmarks, "station_60s_reps")
    if reps_60s is not None:
        assessments["station_60s_reps"] = {
            "value": reps_60s,
            "grade": _grade_high_good(reps_60s, strong=40, weak=20),
        }
    else:
        gaps.append("no station_60s_reps benchmark")

    row_500 = _bench(benchmarks, "row_500m_sec")
    if row_500 is not None:
        assessments["row_500m_sec"] = {
            "value": row_500,
            "grade": _grade_low_good(row_500, strong=100, weak=120),
        }
    else:
        gaps.append("no row_500m_sec benchmark")

    ski_500 = _bench(benchmarks, "ski_500m_sec")
    if ski_500 is not None:
        assessments["ski_500m_sec"] = {
            "value": ski_500,
            "grade": _grade_low_good(ski_500, strong=105, weak=125),
        }
    else:
        gaps.append("no ski_500m_sec benchmark")

    if assessments:
        return {"source": "benchmarks", "assessments": assessments, "data_gaps": gaps}

    # No benchmarks: fall back to an HR proxy from strength sessions. This cannot
    # measure strength, so it is explicitly flagged low-confidence.
    proxy = _hr_proxy_from_strength(activities)
    return {
        "source": "hr_proxy",
        "assessments": proxy,
        "confidence": "low",
        "note": _HR_PROXY_NOTE,
        "data_gaps": ["no strength benchmarks"],
    }


def _hr_proxy_from_strength(activities: list) -> dict:
    """Aggregate strength_training HR as a weak proxy (not a strength measure)."""
    sessions = [a for a in activities if getattr(a, "activity_type", "") == "strength_training"]
    if not sessions:
        return {"strength_sessions": 0, "avg_pct_hrmax": None}

    pcts = []
    for a in sessions:
        avg_hr = getattr(a, "avg_hr", None)
        max_hr = getattr(a, "max_hr", None)
        if avg_hr and max_hr:
            pcts.append(avg_hr / max_hr * 100.0)
    avg_pct = round(sum(pcts) / len(pcts), 1) if pcts else None
    return {"strength_sessions": len(sessions), "avg_pct_hrmax": avg_pct}


def compute_hybrid_balance(profile, hyrox_results: list, benchmarks: dict | None) -> dict:
    """Compare a running index (from profile) against a strength index.

    run_index uses VO2max scaled into 0-100 plus a lactate-threshold-speed nudge.
    strength_index uses station percentiles (if a race exists) and/or benchmarks.
    With neither, strength_index is None and confidence is low.
    """
    vo2 = getattr(profile, "vo2_max", None)
    lt_speed = getattr(profile, "lactate_threshold_speed", None)

    run_index = None
    if vo2 is not None:
        run_index = _clamp((vo2 - 40.0) / 25.0 * 100.0)
        if lt_speed is not None:
            # LT speed ~3.0-4.5 m/s for trained athletes; nudge +/- around midpoint.
            run_index = _clamp(run_index + (lt_speed - 3.5) * 10.0)
        run_index = round(run_index, 1)

    strength_index = None
    confidence = "high"

    station_data = compute_station_percentiles(hyrox_results)
    if station_data.get("available"):
        pcts = [s["percentile"] for s in station_data["stations"].values()]
        if pcts:
            strength_index = round(sum(pcts) / len(pcts), 1)

    bench_grades = compute_strength_endurance(benchmarks, []).get("assessments", {})
    if strength_index is None and benchmarks and bench_grades:
        score_map = {"strong": 80.0, "moderate": 55.0, "weak": 30.0}
        scores = [score_map[v["grade"]] for v in bench_grades.values() if "grade" in v]
        if scores:
            strength_index = round(sum(scores) / len(scores), 1)

    if strength_index is None:
        confidence = "low"

    if run_index is None or strength_index is None:
        balance = "unknown"
        lagging_side = None
    else:
        diff = run_index - strength_index
        if diff > 10:
            balance = "run-dominant"
            lagging_side = "strength"
        elif diff < -10:
            balance = "strength-dominant"
            lagging_side = "run"
        else:
            balance = "balanced"
            lagging_side = None

    return {
        "run_index": run_index,
        "strength_index": strength_index,
        "balance": balance,
        "lagging_side": lagging_side,
        "confidence": confidence,
    }


def _collect_data_gaps(hyrox_results: list, benchmarks: dict | None, profile) -> list[str]:
    gaps = []
    if not hyrox_results:
        gaps.append("no HYROX result")
    if not benchmarks:
        gaps.append("no strength benchmarks")
    weight = getattr(profile, "weight_kg", None) if profile is not None else None
    if weight is None and _bench(benchmarks, "bodyweight_kg") is None:
        gaps.append("no bodyweight")
    return gaps


def compute_strength_hyrox(
    hyrox_results: list,
    benchmarks: dict | None,
    profile,
    activities: list,
    details: dict,
    gender: str = "M",
) -> dict:
    """Entry point: compute all strength/HYROX metrics as a JSON-serializable dict."""
    report = StrengthHyroxReport(
        station_percentiles=compute_station_percentiles(hyrox_results, gender=gender),
        compromised_run_race=compute_compromised_run_race(hyrox_results),
        transition_cost=compute_transition_cost(hyrox_results),
        anaerobic_capacity=compute_anaerobic_capacity(activities),
        strength_endurance=compute_strength_endurance(benchmarks, activities),
        hybrid_balance=compute_hybrid_balance(profile, hyrox_results, benchmarks),
        data_gaps=_collect_data_gaps(hyrox_results, benchmarks, profile),
    )
    return report.to_dict()
