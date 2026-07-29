"""actions.fitness() end to end over real fixture data — no engine mocks.

fitness() is the only place where durability, curves, enviro, load, compliance,
strength, limiters and insights meet. Each is unit-tested on its own, so the
failure this file exists to catch is a *shape* mismatch between one engine's
output and the next engine's (or the web Fitness tab's) expectation.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, Workout, WorkoutType
from paceforge.models.profile import RecentActivity, UserFitnessProfile

MAX_HR = 190
RESTING_HR = 48
N_RUNS = 20  # every 3rd day over ~60 days — enough timeline for CTL/ATL + ACWR


def _activity(i: int, when: datetime) -> RecentActivity:
    return RecentActivity(
        activity_id=9000 + i,
        name=f"Easy run {i}",
        activity_type="running",
        start_time=when,
        distance_meters=9000.0,
        duration_seconds=2700.0,
        avg_hr=140,
        max_hr=158,
        avg_pace_sec_per_km=300.0,
        training_effect_aerobic=2.8,
        training_effect_anaerobic=0.4,
        avg_running_cadence=176.0,
        avg_stride_length=1.12,
        avg_ground_contact_time=252.0,
        avg_vertical_ratio=7.4,
        elevation_gain=40.0,
    )


def _detail(activity_id: int) -> dict:
    # 45 one-minute samples with mild HR drift against near-constant pace — the
    # shape decoupling/curves need to produce a real (non-null) number.
    series = [
        {"t": s * 60, "hr": 132 + round(s * 0.4), "pace": 330.0 + s * 0.3,
         "cad": 176, "stride": 1.12}
        for s in range(45)
    ]
    splits = [
        {"n": n + 1, "distance_m": 1000.0, "duration_s": 330.0 + n * 1.5,
         "pace_sec": 330.0 + n * 1.5, "avg_hr": 136.0 + n, "max_hr": 152.0,
         "elev_gain": 4.0, "avg_cadence": 176.0}
        for n in range(9)
    ]
    hr_zones = [{"zone": z, "secs": secs, "low": low}
                for z, secs, low in ((1, 300.0, 93), (2, 1800.0, 121), (3, 600.0, 140))]
    return {"activity_id": activity_id, "v": 3, "series": series, "splits": splits,
            "hr_zones": hr_zones,
            "weather": {"temp_c": 14.0, "feels_c": 13.0, "humidity": 70, "desc": "cloudy"}}


def _history_row(day: date) -> dict:
    return {"date": day.isoformat(), "vo2_max": 52.0, "resting_hr": RESTING_HR,
            "max_hr": MAX_HR, "hrv_status": "Balanced", "hrv_last_night": 68.0,
            "training_readiness": 72.0, "training_status": "Productive",
            "training_load_7day": 420.0, "load_focus": "High Aerobic",
            "body_battery_current": 65, "body_battery_high": 92, "body_battery_low": 22,
            "sleep_score": 78, "sleep_duration_seconds": 27000.0,
            "sleep_deep_seconds": 4800.0, "sleep_rem_seconds": 5400.0,
            "sleep_light_seconds": 15600.0, "stress_avg": 28, "stress_high": 70,
            "weekly_mileage_km": 45.0, "hill_score": 61.0,
            "respiration_avg_sleep": 13.5, "spo2_avg": 95.0}


@pytest.fixture()
def report(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    today = date.today()

    store.save_profile(UserFitnessProfile(
        vo2_max=52.0, resting_hr=RESTING_HR, max_hr=MAX_HR, training_readiness=72.0,
        training_status="Productive", hrv_status="Balanced", hrv_last_night=68.0,
        weekly_mileage_km=45.0, weight_kg=72.0, body_battery_current=65,
        sleep_score=78, stress_avg=28, profile_date=today,
    ))

    activities = [_activity(i, datetime.combine(today - timedelta(days=3 * i),
                                                datetime.min.time()).replace(hour=7))
                  for i in range(N_RUNS)]
    store.save_activities(activities)
    for a in activities:
        store.save_detail(a.activity_id, _detail(a.activity_id))

    (tmp_path / "history.jsonl").write_text(
        "\n".join(json.dumps(_history_row(today - timedelta(days=d)))
                  for d in range(60, -1, -1)) + "\n")

    store.save_plan(TrainingPlan(
        name="Fixture plan", goal_type="MARATHON", target_date=today + timedelta(days=60),
        total_weeks=12, vdot=50.0, accepted=True,
        weeks=[{"week_number": 1, "workouts": [
            Workout(name="Easy", workout_type=WorkoutType.EASY_RUN, sport="run",
                    scheduled_date=today, estimated_duration_seconds=2700,
                    estimated_distance_meters=9000),
            Workout(name="Long", workout_type=WorkoutType.LONG_RUN, sport="run",
                    scheduled_date=today + timedelta(days=3),
                    estimated_duration_seconds=5400, estimated_distance_meters=18000),
        ]}],
    ))
    store.save_sync_status({"last_success": datetime.now().isoformat(timespec="seconds")})

    return actions.fitness()


def test_fitness_returns_the_full_web_contract(report):
    """Every block the Fitness tab reads is present in one real run."""
    assert set(report) >= {"running", "load", "strength", "compliance", "pace_insights",
                           "insights", "limiters", "headline", "this_week", "data_gaps",
                           "coach_input"}


def test_fitness_payload_is_json_serialisable(report):
    """The runner hands this straight to the browser, so it must survive json.dumps."""
    assert json.loads(json.dumps(report, default=str))["headline"] == report["headline"]


def test_fitness_grafts_pace_curves_onto_the_running_block(report):
    """compute_pace_curves() output is injected into compute_running_metrics()'s dict."""
    assert "pace_curves" in report["running"]


def test_coach_input_decoupling_comes_from_the_durability_block(report):
    """A durability rename would silently null this key — assert the real value flows."""
    assert report["coach_input"]["key_metrics"]["decoupling_pct"] == \
        report["running"]["decoupling"]["average_pct"]


def test_coach_input_ctl_comes_from_the_load_block(report):
    """Same wiring check across the load engine's nested availability dict."""
    assert report["coach_input"]["key_metrics"]["ctl"] == report["load"]["ctl_atl_tsb"]["ctl"]


def test_effective_vo2max_feeds_the_limiter_ranking(report):
    """fitness() prefers the conditions-adjusted VO2max over the raw profile figure."""
    eff = report["running"]["effective_vo2max"]
    expected = eff["current"] if eff.get("available") else 52.0
    assert report["coach_input"]["key_metrics"]["vo2max"] == expected


def test_compliance_is_computed_when_a_plan_exists(report):
    assert report["compliance"] is not None


def test_pace_insights_are_computed_when_the_plan_has_weeks(report):
    assert report["pace_insights"] is not None


def test_insights_verdict_is_derived_from_load_and_running(report):
    assert report["insights"]["verdict"]
