"""Synthetic tests for the strength / HYROX assessment engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from paceforge.engine.strength import (
    compute_anaerobic_capacity,
    compute_compromised_run_race,
    compute_station_percentiles,
    compute_strength_endurance,
    compute_strength_hyrox,
    compute_transition_cost,
)


@dataclass
class _Profile:
    vo2_max: float | None = 50.0
    lactate_threshold_speed: float | None = 3.5
    weight_kg: float | None = 75.0


@dataclass
class _Activity:
    activity_type: str = "running"
    start_time: datetime = datetime.now()
    training_effect_anaerobic: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None


def _split(name, t):
    return {"name": name, "time_seconds": t}


def _race(splits):
    return {"event_date": "Dublin 2025", "division": "HYROX", "splits": splits}


def _even_runs():
    # All runs equal so run-fade is ~0 unless overridden.
    return [_split(f"Running_{i}", 250.0) for i in range(1, 9)]


def _all_station_medians():
    from paceforge.engine.strength import STATION_MEDIANS

    return [_split(name, median) for name, median in STATION_MEDIANS.items()]


# --- station percentiles ---------------------------------------------------


def test_station_percentile_flags_slow_station_as_weakest():
    splits = _even_runs() + _all_station_medians()
    # Make SkiErg much slower than its median -> should rank as weakest.
    splits = [s for s in splits if s["name"] != "SkiErg_1000m"]
    splits.append(_split("SkiErg_1000m", 464.0))  # 2x median
    out = compute_station_percentiles([_race(splits)])
    assert out["weakest_3"][0] == "SkiErg_1000m"


def test_station_at_cohort_average_is_fiftieth_percentile():
    # Medians now come from the shared cohort benchmarks (Men/Open field averages).
    from paceforge.hyrox.benchmarks import get_benchmarks

    field = get_benchmarks("M")["field_avg"]
    splits = _even_runs() + [_split("Row_1000m", field["Row_1000m"])]
    out = compute_station_percentiles([_race(splits)])
    assert out["stations"]["Row_1000m"]["percentile"] == 50.0


def test_station_percentiles_unavailable_without_race():
    assert compute_station_percentiles([]) == {"available": False}


# --- compromised run / run-fade -------------------------------------------


def test_run_fade_math_on_synthetic_splits():
    runs = [
        _split("Running_1", 100.0),
        _split("Running_2", 100.0),
        _split("Running_3", 110.0),
        _split("Running_4", 110.0),
        _split("Running_5", 120.0),
        _split("Running_6", 120.0),
        _split("Running_7", 120.0),
        _split("Running_8", 120.0),
    ]
    out = compute_compromised_run_race([_race(runs)])
    # opening mean 100, closing mean 120 -> 20% fade.
    assert out["fade_pct"] == 20.0


def test_run_fade_grade_elite_when_no_fade():
    out = compute_compromised_run_race([_race(_even_runs())])
    assert out["grade"] == "elite"


def test_run_fade_unavailable_without_race():
    assert compute_compromised_run_race([]) == {"available": False}


# --- transition cost -------------------------------------------------------


def test_roxzone_good_grade_under_five_min():
    out = compute_transition_cost([_race([_split("Roxzone_Time", 240.0)])])
    assert out["roxzone_sec"] == 240.0 and out["grade"] == "good"


def test_roxzone_bleeding_grade_over_eight_min():
    out = compute_transition_cost([_race([_split("Roxzone_Time", 540.0)])])
    assert out["grade"] == "bleeding"


# --- anaerobic capacity ----------------------------------------------------


def test_anaerobic_te_counts_only_recent_high_sessions():
    now = datetime.now()
    acts = [
        _Activity(start_time=now - timedelta(days=1), training_effect_anaerobic=3.5),
        _Activity(start_time=now - timedelta(days=5), training_effect_anaerobic=4.0),
        _Activity(start_time=now - timedelta(days=2), training_effect_anaerobic=2.0),  # too low
        _Activity(start_time=now - timedelta(days=40), training_effect_anaerobic=4.5),  # too old
    ]
    out = compute_anaerobic_capacity(acts)
    assert out["anaerobic_te_sessions_28d"] == 2


def test_anaerobic_under_stimulated_when_none():
    assert compute_anaerobic_capacity([])["signal"] == "under-stimulated"


# --- strength endurance ----------------------------------------------------


def test_benchmark_grading_strong_wall_balls():
    out = compute_strength_endurance({"wall_balls_max": 60}, [])
    assert out["source"] == "benchmarks"
    assert out["assessments"]["wall_balls_max"]["grade"] == "strong"


def test_strength_endurance_hr_proxy_is_low_confidence():
    acts = [_Activity(activity_type="strength_training", avg_hr=140, max_hr=180)]
    out = compute_strength_endurance(None, acts)
    assert out["source"] == "hr_proxy"
    assert out["confidence"] == "low"
    assert out["note"] == "HR-only proxy, not a strength measure"


# --- hybrid balance & full report -----------------------------------------


def test_hybrid_balance_unknown_and_low_confidence_without_strength_data():
    out = compute_strength_hyrox([], None, _Profile(), [], {})
    hb = out["hybrid_balance"]
    assert hb["balance"] == "unknown"
    assert hb["confidence"] == "low"
    assert hb["strength_index"] is None


def test_hybrid_balance_has_strength_index_with_benchmarks():
    benchmarks = {"wall_balls_max": 60, "sandbag_lunges_max": 45}
    out = compute_strength_hyrox([], benchmarks, _Profile(), [], {})
    hb = out["hybrid_balance"]
    assert hb["strength_index"] is not None
    assert hb["confidence"] == "high"


def test_no_race_no_benchmarks_populates_data_gaps_without_crash():
    out = compute_strength_hyrox([], None, _Profile(weight_kg=None), [], {})
    gaps = out["data_gaps"]
    assert "no HYROX result" in gaps
    assert "no strength benchmarks" in gaps
    assert "no bodyweight" in gaps
    assert out["station_percentiles"] == {"available": False}
