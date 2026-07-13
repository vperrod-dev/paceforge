"""brief() — the daily ntfy morning-brief text."""

from __future__ import annotations

from datetime import date

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout
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
