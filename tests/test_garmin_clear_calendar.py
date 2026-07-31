"""garmin_clear_calendar() removes scheduled workouts from today onwards only."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, scheduled, fail_ids: set[int] | None = None):
        self._scheduled = scheduled
        self.deleted: list[int] = []
        self.fail_ids = fail_ids or set()

    def get_scheduled_workouts(self, days_ahead: int = 400):
        return self._scheduled

    def delete_workout(self, workout_id):  # noqa: ANN001
        if int(workout_id) in self.fail_ids:
            raise RuntimeError("garmin down")
        self.deleted.append(int(workout_id))
        return True


def _sched():
    y = (date.today() - timedelta(days=2)).isoformat()
    t = date.today().isoformat()
    f = (date.today() + timedelta(days=5)).isoformat()
    return [
        {"workout_id": 11, "scheduled_date": y, "name": "past"},
        {"workout_id": 22, "scheduled_date": t, "name": "today"},
        {"workout_id": 33, "scheduled_date": f, "name": "future"},
        {"workout_id": 33, "scheduled_date": f, "name": "dupe"},  # same id, once
    ]


def test_dry_run_lists_future_without_deleting():
    fake = _FakeClient(_sched())
    result = actions.garmin_clear_calendar(dry_run=True, client=fake)
    assert result["dry_run"] is True
    assert result["count"] == 2  # today + future, deduped
    assert fake.deleted == []


def test_deletes_from_today_onwards_only():
    fake = _FakeClient(_sched())
    result = actions.garmin_clear_calendar(client=fake)
    assert result["deleted"] == 2
    assert sorted(fake.deleted) == [22, 33]  # past (11) untouched


def _plan_with_future_ids() -> TrainingPlan:
    workouts = [
        Workout(workout_type=WorkoutType.EASY_RUN, name=f"w{wid}", garmin_workout_id=wid,
                scheduled_date=date.today() + timedelta(days=5))
        for wid in (22, 33)
    ]
    return TrainingPlan(
        name="P", goal_type="HYROX", target_date=date.today() + timedelta(weeks=8),
        total_weeks=1, weeks=[TrainingWeek(week_number=1, workouts=workouts)],
    )


def test_failed_delete_keeps_plan_id_for_retry():
    store.save_plan(_plan_with_future_ids())

    actions.garmin_clear_calendar(client=_FakeClient(_sched(), fail_ids={33}))

    saved = store.load_plan()
    assert [w.garmin_workout_id for wk in saved.weeks for w in wk.workouts] == [None, 33]


def test_failed_delete_is_reported_not_counted_as_deleted():
    result = actions.garmin_clear_calendar(client=_FakeClient(_sched(), fail_ids={33}))
    assert (result["deleted"], result["failed"]) == (1, 1)
