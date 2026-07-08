"""Tests for pace insights and recalibration."""

from __future__ import annotations

from datetime import date, timedelta

from paceforge.engine.compliance import pace_metrics, pace_status
from paceforge.engine.vdot import paces_from_vdot
from paceforge.engine.workouts import WorkoutFactory


def _tempo(scheduled=None):
    w = WorkoutFactory(paces_from_vdot(52)).tempo(6)
    w.scheduled_date = scheduled
    return w


def _detail(pace_sec, n=10, hr=150, temp=None):
    return {
        "splits": [
            {"n": i, "distance_m": 1000, "pace_sec": pace_sec + i, "avg_hr": hr}
            for i in range(n)
        ],
        "weather": {"temp_c": temp, "humidity": None},
    }


def test_within_band_when_on_target():
    w = _tempo()
    p = paces_from_vdot(52)
    m = pace_metrics(w, _detail(p.threshold))
    assert m and m["within_band"] and not m["ahead"]


def test_ahead_when_faster_than_window():
    w = _tempo()
    p = paces_from_vdot(52)
    m = pace_metrics(w, _detail(p.threshold - 20))
    assert m and m["ahead"]


def test_ahead_withheld_when_hr_redlined():
    w = _tempo()
    p = paces_from_vdot(52)
    m = pace_metrics(w, _detail(p.threshold - 20, hr=185), lt_hr=165)
    assert m and not m["ahead"]


def test_heat_adjustment_rescues_hot_day():
    w = _tempo()
    p = paces_from_vdot(52)
    slow = p.threshold + 12  # slow on the clock…
    cool = pace_metrics(w, _detail(slow))
    hot = pace_metrics(w, _detail(slow, temp=30))
    assert hot["pace_actual_sec"] < cool["pace_actual_sec"]


def test_easy_runs_ignored():
    w = WorkoutFactory(paces_from_vdot(52)).easy_run(8)
    assert pace_metrics(w, _detail(300)) is None


def _judged_plan(deltas, days_apart=5):
    """Plan with 5 judged tempos spread over deltas (sec vs mid)."""
    from paceforge.models.plan import TrainingPlan, TrainingWeek

    p = paces_from_vdot(52)
    workouts = []
    start = date.today() - timedelta(days=days_apart * len(deltas))
    for i, d in enumerate(deltas):
        w = _tempo(scheduled=start + timedelta(days=i * days_apart))
        lo, hi = p.band("threshold")
        actual = (lo + hi) / 2 + d
        w.completion_metrics = {
            "pace_delta_sec": d,
            "within_band": lo <= actual <= hi,
            "ahead": actual < lo,
        }
        workouts.append(w)
    return TrainingPlan(
        name="t", goal_type="HALF_MARATHON", target_date=date.today() + timedelta(weeks=8),
        total_weeks=8, weeks=[TrainingWeek(week_number=1, workouts=workouts)],
    )


def test_status_ahead_needs_four_of_five_over_three_weeks():
    plan = _judged_plan([-15, -15, -15, -15, 0], days_apart=6)
    assert pace_status(plan)["status"] == "ahead"


def test_status_monitoring_when_window_too_short():
    plan = _judged_plan([-15, -15, -15, -15, 0], days_apart=2)
    assert pace_status(plan)["status"] == "monitoring"


def test_status_review_when_consistently_slow():
    plan = _judged_plan([15, 15, 15, 0, 0], days_apart=6)
    assert pace_status(plan)["status"] == "review"


def test_recalibrate_retargets_future_only(tmp_path, monkeypatch):
    import paceforge.actions as actions
    from paceforge import store
    from paceforge.models.plan import TrainingPlan, TrainingWeek

    p = paces_from_vdot(52)
    past = _tempo(scheduled=date.today() - timedelta(days=7))
    future = _tempo(scheduled=date.today() + timedelta(days=7))
    old_future_low = future.steps[1].target_low
    plan = TrainingPlan(
        name="t", goal_type="HALF_MARATHON", target_date=date.today() + timedelta(weeks=8),
        total_weeks=8, vdot=52.0, threshold_pace=p.threshold,
        weeks=[TrainingWeek(week_number=1, workouts=[past, future])],
    )
    saved = {}
    monkeypatch.setattr(store, "load_plan", lambda: plan)
    monkeypatch.setattr(store, "save_plan", lambda pl: saved.update(plan=pl))
    monkeypatch.setattr(store, "load_profile", lambda: None)
    out = actions.recalibrate(0.5)
    assert out["vdot"] == 52.5
    assert future.steps[1].target_low < old_future_low  # faster
    assert past.steps[1].target_low == old_future_low  # untouched
    assert saved


def test_recalibrate_frozen_near_race(monkeypatch):
    import pytest

    import paceforge.actions as actions
    from paceforge import store
    from paceforge.models.plan import TrainingPlan, TrainingWeek

    plan = TrainingPlan(
        name="t", goal_type="HALF_MARATHON", target_date=date.today() + timedelta(days=10),
        total_weeks=8, vdot=52.0,
        weeks=[TrainingWeek(week_number=1, workouts=[_tempo(date.today() + timedelta(days=2))])],
    )
    monkeypatch.setattr(store, "load_plan", lambda: plan)
    with pytest.raises(RuntimeError, match="frozen"):
        actions.recalibrate(0.5)


def test_recalibrate_rate_limited(monkeypatch):
    import pytest

    import paceforge.actions as actions
    from paceforge import store
    from paceforge.models.plan import TrainingPlan, TrainingWeek

    plan = TrainingPlan(
        name="t", goal_type="HALF_MARATHON", target_date=date.today() + timedelta(weeks=8),
        total_weeks=8, vdot=52.0,
        last_recalibration=(date.today() - timedelta(days=7)).isoformat(),
        weeks=[TrainingWeek(week_number=1, workouts=[_tempo(date.today() + timedelta(days=2))])],
    )
    monkeypatch.setattr(store, "load_plan", lambda: plan)
    with pytest.raises(RuntimeError, match="4 weeks"):
        actions.recalibrate(0.5)
