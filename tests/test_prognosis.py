"""Race prognosis: effective VO2max, shape correction, verdicts."""

from datetime import datetime, timedelta

from paceforge.engine.prognosis import compute_prognosis
from paceforge.models.profile import RecentActivity, UserFitnessProfile

PROFILE = UserFitnessProfile(max_hr=190)


def _run(days_ago: int, pace: float = 300.0, hr: int = 150, km: float = 10.0) -> RecentActivity:
    return RecentActivity(
        activity_id=1000 + days_ago,
        name="run",
        activity_type="running",
        start_time=datetime.now() - timedelta(days=days_ago),
        distance_meters=km * 1000,
        duration_seconds=pace * km,
        avg_hr=hr,
        avg_pace_sec_per_km=pace,
    )


def test_effective_vo2max_in_plausible_range():
    out = compute_prognosis([_run(d) for d in (2, 5, 9)], {}, PROFILE)
    assert 40 <= out["effective_vo2max"] <= 60


def test_recent_fast_runs_raise_vo2max_vs_same_runs_older():
    fast_recent = [_run(3, pace=270), _run(80, pace=330)]
    fast_old = [_run(3, pace=330), _run(80, pace=270)]
    a = compute_prognosis(fast_recent, {}, PROFILE)["effective_vo2max"]
    b = compute_prognosis(fast_old, {}, PROFILE)["effective_vo2max"]
    assert a > b


def test_shape_factor_penalizes_low_mileage():
    high = [_run(d) for d in range(1, 56, 2)]  # ~35 km/wk
    low = [_run(d) for d in (5, 20, 40)]  # ~3.75 km/wk
    hi = compute_prognosis(high, {}, PROFILE)["shape"]["factor"]
    lo = compute_prognosis(low, {}, PROFILE)["shape"]["factor"]
    assert hi > lo


def test_prognosis_slower_when_shape_lower():
    high = [_run(d) for d in range(1, 56, 2)]
    low = [_run(d) for d in (5, 20, 40)]
    hi = compute_prognosis(high, {}, PROFILE)["prognosis_time_sec"]
    lo = compute_prognosis(low, {}, PROFILE)["prognosis_time_sec"]
    assert lo > hi  # same per-run fitness, less volume → slower prognosis


def test_goal_slower_than_prognosis_is_on_track():
    runs = [_run(d) for d in (2, 5, 9)]
    prog = compute_prognosis(runs, {}, PROFILE)["prognosis_time_sec"]
    out = compute_prognosis(runs, {}, PROFILE, goal_time_sec=prog + 60)
    assert out["goal_verdict"] == "on_track"


def test_goal_within_3pct_faster_is_stretch():
    runs = [_run(d) for d in (2, 5, 9)]
    prog = compute_prognosis(runs, {}, PROFILE)["prognosis_time_sec"]
    out = compute_prognosis(runs, {}, PROFILE, goal_time_sec=prog * 0.98)
    assert out["goal_verdict"] == "stretch"


def test_goal_beyond_3pct_faster_is_unrealistic():
    runs = [_run(d) for d in (2, 5, 9)]
    prog = compute_prognosis(runs, {}, PROFILE)["prognosis_time_sec"]
    out = compute_prognosis(runs, {}, PROFILE, goal_time_sec=prog * 0.9)
    assert out["goal_verdict"] == "unrealistic"


def test_no_activities_means_unavailable():
    out = compute_prognosis([], {}, PROFILE)
    assert out["available"] is False


def test_prior_vdot_clamps_inflated_hr_estimate():
    # Low-HR easy runs inflate the Swain-derived estimate; a stated-race prior
    # anchors it to prior x [0.90, 1.12].
    acts = [_run(d, pace=290.0, hr=132, km=6.0) for d in range(1, 15, 2)]
    anchored = compute_prognosis(acts, {}, PROFILE, prior_vdot=38.0)
    assert anchored["available"]
    assert 38.0 * 0.90 - 0.05 <= anchored["effective_vo2max"] <= 38.0 * 1.12 + 0.05
