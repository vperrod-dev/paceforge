"""garmin_reconcile() — the Garmin calendar mirrors the plan from today forward."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, scheduled=None, fail_ids=None):
        self.deleted: list[int] = []
        self.pushed_weeks: list[list[str]] = []
        self.scheduled = scheduled or []
        self.fail_ids = fail_ids or set()
        self._next_id = 1000

    def delete_workout(self, workout_id):  # noqa: ANN001
        if int(workout_id) in self.fail_ids:
            raise RuntimeError("garmin down")
        self.deleted.append(int(workout_id))
        return True

    def push_plan_week(self, workouts, plan_paces=None, pace_bands=None):  # noqa: ANN001
        self.pushed_weeks.append([w.name for w in workouts])
        for w in workouts:
            self._next_id += 1
            w.garmin_workout_id = self._next_id
        return {"pushed": [{"name": w.name} for w in workouts], "failed": []}

    def get_scheduled_workouts(self, days_ahead=30):  # noqa: ANN001
        return self.scheduled


def _workout(name: str, day_offset: int, **kwargs) -> Workout:
    return Workout(workout_type=WorkoutType.EASY_RUN, name=name,
                   scheduled_date=date.today() + timedelta(days=day_offset), **kwargs)


def _plan() -> TrainingPlan:
    return TrainingPlan(
        name="test", goal_type="MARATHON", target_date=date.today() + timedelta(days=90),
        total_weeks=5, accepted=True,
        weeks=[
            TrainingWeek(week_number=1, workouts=[
                _workout("done last week", -7, completed=True, garmin_workout_id=77),
            ]),
            TrainingWeek(week_number=2, workouts=[_workout("current tue", 1)]),
            TrainingWeek(week_number=3, workouts=[_workout("next tue", 8)]),
            TrainingWeek(week_number=4, workouts=[_workout("later tue", 15)]),
            TrainingWeek(week_number=5, workouts=[_workout("way later tue", 22)]),
        ],
    )


def _scheduled(wid: int, day_offset: int) -> dict:
    return {"workout_id": wid,
            "scheduled_date": (date.today() + timedelta(days=day_offset)).isoformat(),
            "name": f"w{wid}"}


def test_pushes_current_plus_next_two_weeks():
    store.save_plan(_plan())
    fake = _FakeClient()
    result = actions.garmin_reconcile(client=fake)
    assert fake.pushed_weeks == [["current tue"], ["next tue"], ["later tue"]]
    assert result["pushed"] == 3


def test_orphan_scheduled_workout_is_deleted():
    store.save_plan(_plan())
    fake = _FakeClient(scheduled=[_scheduled(555, 3)])  # not any plan workout's id
    result = actions.garmin_reconcile(client=fake)
    assert 555 in fake.deleted
    assert result["orphans_deleted"] == 1


def test_plan_owned_id_is_kept():
    store.save_plan(_plan())
    fake = _FakeClient()
    # push assigns ids 1001..1003; 1001 belongs to "current tue" after the push
    fake.scheduled = [_scheduled(1001, 1)]
    result = actions.garmin_reconcile(client=fake)
    assert 1001 not in fake.deleted
    assert result["orphans_deleted"] == 0


def test_past_scheduled_entry_is_left_alone():
    store.save_plan(_plan())
    fake = _FakeClient(scheduled=[_scheduled(555, -3)])  # orphan id, but in the past
    result = actions.garmin_reconcile(client=fake)
    assert 555 not in fake.deleted
    assert result["orphans_deleted"] == 0


def test_stale_completed_copy_deleted_and_cleared():
    store.save_plan(_plan())
    fake = _FakeClient()
    result = actions.garmin_reconcile(client=fake)
    assert result["stale_deleted"] == 1
    assert 77 in fake.deleted
    assert store.load_plan().weeks[0].workouts[0].garmin_workout_id is None


def test_failed_stale_delete_keeps_id_for_next_run():
    store.save_plan(_plan())
    fake = _FakeClient(fail_ids={77})
    result = actions.garmin_reconcile(client=fake)
    assert (result["stale_deleted"], result["delete_failed"]) == (0, 1)
    assert store.load_plan().weeks[0].workouts[0].garmin_workout_id == 77


def test_failed_orphan_delete_is_reported_not_counted():
    store.save_plan(_plan())
    fake = _FakeClient(scheduled=[_scheduled(555, 3)], fail_ids={77, 555})
    result = actions.garmin_reconcile(client=fake)
    assert (result["orphans_deleted"], result["delete_failed"]) == (0, 2)
