"""Rules in engine/insights.py — each threshold produces the right severity + advice."""

from __future__ import annotations

from paceforge.engine.insights import daily_insights

GREEN_LOAD = {"readiness_composite": {"score": 80, "band": "high", "dominant_driver": "hrv"}}


def test_illness_alert_dominates_verdict():
    load = {**GREEN_LOAD, "illness_watch": {"level": "alert", "signals": ["hrv_below"]}}
    out = daily_insights({}, load, {})
    assert out["verdict"]["band"] == "red"


def test_deep_negative_tsb_is_red():
    out = daily_insights({}, {"ctl_atl_tsb": {"tsb": -35}}, {})
    assert any(i["severity"] == "red" and i["area"] == "load" for i in out["items"])


def test_acwr_spike_flags_injury_risk():
    out = daily_insights({}, {"acwr": {"acwr": 1.6}}, {})
    assert any("injury risk" in i["evidence"] for i in out["items"])


def test_sleep_debt_names_a_bedtime_shift():
    out = daily_insights({}, {"sleep": {"sleep_debt_hours": 7.0}}, {})
    assert any("bed" in i["advice"] and "min earlier" in i["advice"] for i in out["items"])


def test_low_readiness_with_quality_session_suggests_swap():
    load = {"readiness_composite": {"score": 30, "band": "low", "dominant_driver": "sleep"}}
    out = daily_insights({}, load, {}, todays_type="tempo")
    assert "swap" in out["verdict"]["action"].lower()


def test_green_day_says_go():
    out = daily_insights({}, GREEN_LOAD, {}, todays_type="intervals")
    assert out["verdict"]["band"] == "green"


def test_stale_data_flagged_after_36h():
    out = daily_insights({}, GREEN_LOAD, {}, last_sync="2020-01-01T06:00:00+00:00")
    assert out["stale"] is True
