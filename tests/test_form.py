"""Form trends + recovery-HR mining."""

from __future__ import annotations

from datetime import datetime, timedelta

from paceforge.engine.form import _hrr_events, compute_form, compute_recovery_hr
from paceforge.models.profile import RecentActivity


def _run(aid, days_ago, cad, stride=95.0, gct=260.0, vr=8.0):
    return RecentActivity(
        activity_id=aid, name="run", activity_type="running",
        start_time=datetime.now() - timedelta(days=days_ago),
        distance_meters=5000, duration_seconds=1500,
        avg_running_cadence=cad, avg_stride_length=stride,
        avg_ground_contact_time=gct, avg_vertical_ratio=vr,
    )


def test_form_series_runs_only_with_cadence_normalized():
    acts = [
        _run(1, 2, 82),      # strides/min firmware -> doubled to 164
        _run(2, 4, 170),
        RecentActivity(activity_id=3, name="ride", activity_type="cycling",
                       start_time=datetime.now() - timedelta(days=1),
                       distance_meters=2000, duration_seconds=3600),
    ]
    f = compute_form(acts, {})
    assert len(f["series"]) == 2
    assert {r["cadence"] for r in f["series"]} == {164.0, 170.0}


def test_cadence_current_vs_target():
    f = compute_form([_run(1, 1, 158), _run(2, 3, 160)], {})
    assert f["cadence"]["current"] == 159.0
    assert f["cadence"]["target_lo"] <= f["cadence"]["target_hi"]


def test_hrr_events_detects_drop_after_effort():
    pts = [(0, 120), (15, 150), (30, 165), (45, 160), (60, 150), (90, 128), (120, 118)]
    events = _hrr_events(pts)
    assert events and max(events) >= 30   # 165 @30s -> ~128 @90s


def test_hrr_ignores_low_intensity_and_small_drops():
    flat = [(i * 15, 120) for i in range(20)]           # never above threshold
    assert _hrr_events(flat) == []
    small = [(0, 100), (15, 140), (30, 138), (90, 133)]  # peak below 130... wait 140>130
    # peak 140 but drop only 5 -> no event
    assert _hrr_events(small) == []


def test_recovery_hr_series_per_session():
    act = _run(9, 1, 170)
    details = {9: {"series": [
        {"t": 0, "hr": 110}, {"t": 15, "hr": 155}, {"t": 30, "hr": 168},
        {"t": 45, "hr": 160}, {"t": 60, "hr": 150}, {"t": 95, "hr": 130},
        {"t": 130, "hr": 122}, {"t": 160, "hr": 120},
    ]}}
    r = compute_recovery_hr([act], details)
    assert r["available"] and len(r["series"]) == 1
    assert r["series"][0]["hrr60_best"] >= 30
    assert r["series"][0]["n_efforts"] >= 1
