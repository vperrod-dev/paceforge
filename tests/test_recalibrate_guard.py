"""recalibrate() readiness/HRV guard — no pace bumps while recovering."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _plan() -> TrainingPlan:
    ws = [
        Workout(
            workout_type=WorkoutType.EASY_RUN,
            name="w0",
            scheduled_date=date.today() + timedelta(days=1),
            estimated_distance_meters=6000,
        )
    ]
    return TrainingPlan(
        name="P",
        goal_type="HALF_MARATHON",
        target_date=date.today() + timedelta(weeks=8),
        total_weeks=1,
        easy_pace=300.0,
        vdot=45.0,
        weeks=[TrainingWeek(week_number=1, total_distance_km=30, workouts=ws)],
    )


def test_low_readiness_blocks_positive_recalibration():
    store.save_plan(_plan())
    store.save_profile(UserFitnessProfile(training_readiness=30))
    with pytest.raises(RuntimeError, match="Readiness/HRV is down"):
        actions.recalibrate(0.5)


def test_low_hrv_status_blocks_positive_recalibration():
    store.save_plan(_plan())
    store.save_profile(UserFitnessProfile(training_readiness=80, hrv_status="Low"))
    with pytest.raises(RuntimeError, match="Readiness/HRV is down"):
        actions.recalibrate(0.5)


def test_force_overrides_readiness_guard():
    store.save_plan(_plan())
    store.save_profile(UserFitnessProfile(training_readiness=30, hrv_status="Low"))
    assert actions.recalibrate(0.5, force=True)["vdot"] == 45.5
