"""brief() — the daily Telegram morning-brief text (plain + Telegram-HTML)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from paceforge import actions, store
from paceforge.models.calendar import ScheduledItem
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutStep
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _seed(workout=None):
    store.save_profile(UserFitnessProfile(
        training_readiness=78, sleep_score=82, sleep_duration_seconds=7 * 3600 + 12 * 60,
        hrv_status="Balanced", body_battery_current=90))
    workouts = [workout] if workout else []
    store.save_plan(TrainingPlan(name="t", goal_type="HYROX", target_date=date(2026, 11, 13),
                                 total_weeks=1,
                                 weeks=[TrainingWeek(week_number=1, workouts=workouts)]))


def test_brief_shows_vitals_and_todays_session():
    _seed(Workout(workout_type="tempo", name="Tempo", scheduled_date=date(2026, 6, 1),
                  estimated_distance_meters=8000, briefing={"purpose": "Push the threshold."}))
    text = actions.brief("2026-06-01")
    assert text == ("Readiness 78 · Sleep 82 (7h12) · HRV Balanced · Battery 90\n"
                    "Today: Tempo — 8.0 km. Push the threshold.")


def test_brief_rest_day():
    _seed(Workout(workout_type="rest", name="Rest", scheduled_date=date(2026, 6, 1)))
    assert actions.brief("2026-06-01").endswith("Today: rest day.")


def test_brief_nothing_scheduled():
    _seed()
    assert actions.brief("2026-06-01").endswith("Today: nothing scheduled.")


def _tempo_workout() -> Workout:
    return Workout(
        workout_type="tempo", name="Tempo & Strides", scheduled_date=date(2026, 6, 1),
        estimated_distance_meters=8000,
        steps=[
            WorkoutStep(step_type="warmup", target_type="pace", target_low=330, target_high=350),
            WorkoutStep(step_type="active", target_type="pace", target_low=275, target_high=290),
        ],
        briefing={"purpose": "Push the <threshold>."})


def test_brief_telegram_bold_header_present():
    _seed(_tempo_workout())
    assert "<b>Tempo &amp; Strides</b>" in actions.brief("2026-06-01", fmt="telegram")


def test_brief_telegram_pace_band_from_work_step():
    _seed(_tempo_workout())
    assert "@ 4:35–4:50/km" in actions.brief("2026-06-01", fmt="telegram")


def test_brief_telegram_escapes_user_text():
    _seed(_tempo_workout())
    assert "Push the &lt;threshold&gt;." in actions.brief("2026-06-01", fmt="telegram")


def test_brief_telegram_readiness_verdict_from_fitness_json():
    _seed(_tempo_workout())
    (store.DATA_DIR / "fitness.json").write_text(json.dumps(
        {"load": {"readiness_composite": {"score": 74, "band": "green"}}}))
    assert "📈 <b>Trend</b> 🟢 74 (green)" in actions.brief("2026-06-01", fmt="telegram")


def test_brief_lists_a_booked_class_on_an_otherwise_empty_day():
    _seed()
    store.save_calendar([ScheduledItem(date=date(2026, 6, 1), sport="Cardio",
                                       title="Un1t", duration_min=45)])
    assert actions.brief("2026-06-01").endswith("Today: Un1t (Cardio) — 45 min")


def test_brief_telegram_lists_a_booked_ride():
    _seed()
    store.save_calendar([ScheduledItem(date=date(2026, 6, 1), sport="Bike",
                                       title="Outdoor cycling", duration_min=120)])
    assert "🚴 <b>Outdoor cycling</b> (Bike) — 120 min" in actions.brief("2026-06-01", fmt="telegram")
