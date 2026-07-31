"""garmin_delete() removes every pushed workout from Garmin and clears its id."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.garmin.client import GarminClient
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, fail_ids: set[int] | None = None):
        self.deleted: list[int] = []
        self.fail_ids = fail_ids or set()

    def delete_workout(self, workout_id: int) -> bool:
        if workout_id in self.fail_ids:
            raise RuntimeError("garmin down")
        self.deleted.append(workout_id)
        return True


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

    assert result == {"deleted": 3, "failed": 0}
    assert sorted(fake.deleted) == [100, 101, 102]
    saved = store.load_plan()
    assert all(w.garmin_workout_id is None for wk in saved.weeks for w in wk.workouts)


def test_garmin_delete_keeps_id_when_garmin_delete_fails():
    store.save_plan(_plan_with_ids())

    actions.garmin_delete(client=_FakeClient(fail_ids={101}))

    saved = store.load_plan()
    assert [w.garmin_workout_id for wk in saved.weeks for w in wk.workouts] == [None, 101, None, None]


def test_garmin_delete_reports_failure_count():
    store.save_plan(_plan_with_ids())

    result = actions.garmin_delete(client=_FakeClient(fail_ids={101}))

    assert result == {"deleted": 2, "failed": 1}


def _garmin_client(inner) -> GarminClient:
    client = GarminClient(email="a@example.com", password="x")
    client._client = inner
    return client


def test_client_delete_workout_raises_on_api_error():
    class _Boom:
        def delete_workout(self, wid):  # noqa: ANN001
            raise RuntimeError("garmin down")

    with pytest.raises(RuntimeError, match="garmin down"):
        _garmin_client(_Boom()).delete_workout(42)


def test_client_delete_workout_returns_true_on_success():
    class _Ok:
        def delete_workout(self, wid):  # noqa: ANN001
            return None

    assert _garmin_client(_Ok()).delete_workout(42) is True
