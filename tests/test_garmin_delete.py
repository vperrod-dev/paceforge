"""garmin_delete() removes every pushed workout from Garmin and clears its id."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self):
        self.deleted: list[int] = []

    def delete_workout(self, workout_id: int) -> None:
        self.deleted.append(workout_id)


def _plan_with_ids() -> TrainingPlan:
    pushed = [
        Workout(workout_type=WorkoutType.EASY_RUN, name=f"w{i}", garmin_workout_id=100 + i)
        for i in range(3)
    ]
    pushed.append(Workout(workout_type=WorkoutType.EASY_RUN, name="unpushed"))  # no id
    return TrainingPlan(
        name="P",
        goal_type="HYROX",
        target_date=date.today() + timedelta(weeks=8),
        total_weeks=1,
        weeks=[TrainingWeek(week_number=1, workouts=pushed)],
    )


def test_garmin_delete_removes_tracked_workouts_and_clears_ids():
    store.save_plan(_plan_with_ids())
    fake = _FakeClient()

    result = actions.garmin_delete(client=fake)

    assert result == {"deleted": 3}
    assert sorted(fake.deleted) == [100, 101, 102]
    saved = store.load_plan()
    assert all(w.garmin_workout_id is None for wk in saved.weeks for w in wk.workouts)
