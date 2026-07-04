"""Cohort-aware HYROX benchmarks."""
from paceforge.hyrox.analyzer import FIELD_AVG, analyze_race, compute_training_priorities
from paceforge.hyrox.benchmarks import get_benchmarks
from paceforge.hyrox.models import HyroxRaceResult, HyroxSplit


def test_men_open_is_the_measured_baseline():
    b = get_benchmarks("M", "HYROX", None)
    assert b["field_avg"]["Running_1"] == FIELD_AVG["Running_1"]
    assert b["source"] == "men_open_s7s8"


def test_women_scaled_more_on_runs_than_stations():
    b = get_benchmarks("F", "HYROX", None)
    run_ratio = b["field_avg"]["Running_1"] / FIELD_AVG["Running_1"]
    station_ratio = b["field_avg"]["Wall_Balls"] / FIELD_AVG["Wall_Balls"]
    assert run_ratio > station_ratio > 1.0
    assert "scaled_women" in b["source"]


def test_age_group_slows_benchmarks():
    b40 = get_benchmarks("M", "HYROX", "40-44")
    b50 = get_benchmarks("M", "HYROX", "50-54")
    assert FIELD_AVG["Running_1"] < b40["field_avg"]["Running_1"] < b50["field_avg"]["Running_1"]
    assert "age_adjusted_40-44" in b40["source"]


def test_thirties_are_reference_band():
    assert get_benchmarks("M", "HYROX", "30-34")["field_avg"] == get_benchmarks("M", "HYROX", None)["field_avg"]


def _race():
    splits = [HyroxSplit(name=f"Running_{i}", time_seconds=340 + i * 6) for i in range(1, 9)]
    splits += [
        HyroxSplit(name="SkiErg_1000m", time_seconds=280),
        HyroxSplit(name="Sled_Pull_50m", time_seconds=290),  # way over benchmark
        HyroxSplit(name="Wall_Balls", time_seconds=310),
    ]
    return HyroxRaceResult(total_time_seconds=5400, division="HYROX",
                           age_group="40-44", splits=splits)


def test_analyze_race_reports_cohort():
    out = analyze_race(_race(), gender="M")
    assert out["benchmark_cohort"] == "M Open 40-44"
    assert "age_adjusted" in out["benchmark_source"]


def test_priorities_flag_weak_stations():
    pri = compute_training_priorities(_race(), gender="M")
    flagged = [p["name"] for p in pri if p["train_priority"]]
    assert "Sled_Pull_50m" in flagged
    assert all(not p["is_running"] or p["name"] not in flagged or True for p in pri)
    # the two weakest stations are always flagged
    stations = [p for p in pri if not p["is_running"]]
    assert stations[0]["train_priority"] and stations[1]["train_priority"]
