"""autosync() delegates to garmin_reconcile(): stale cleanup + current & next 2 weeks."""

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
        self.pushed_weeks: list[list[str]] = []
        self._next_id = 1000

    def delete_workout(self, workout_id):  # noqa: ANN001
        self.deleted.append(int(workout_id))
        return True

    def push_plan_week(self, workouts, plan_paces=None, pace_bands=None):  # noqa: ANN001
        self.pushed_weeks.append([w.name for w in workouts])
        for w in workouts:
            self._next_id += 1
            w.garmin_workout_id = self._next_id
        return {"pushed": [{"name": w.name} for w in workouts], "failed": []}

    def get_scheduled_workouts(self, days_ahead=30):  # noqa: ANN001
        return []


def _workout(name: str, day_offset: int, **kwargs) -> Workout:
    return Workout(workout_type=WorkoutType.EASY_RUN, name=name,
                   scheduled_date=date.today() + timedelta(days=day_offset), **kwargs)


def _plan(accepted: bool = True) -> TrainingPlan:
    return TrainingPlan(
        name="test", goal_type="MARATHON", target_date=date.today() + timedelta(days=60),
        total_weeks=4, accepted=accepted,
        weeks=[
            TrainingWeek(week_number=1, workouts=[
                _workout("done last week", -7, completed=True, garmin_workout_id=77),
                _workout("skipped last week", -5),  # not completed — id-less, left alone
            ]),
            TrainingWeek(week_number=2, workouts=[
                _workout("current tue", 1),
                _workout("current sat", 4),
            ]),
            TrainingWeek(week_number=3, workouts=[
                _workout("next tue", 8),
            ]),
            TrainingWeek(week_number=4, workouts=[
                _workout("later tue", 15),
            ]),
        ],
    )


def test_pushes_exactly_the_three_upcoming_weeks():
    store.save_plan(_plan())
    fake = _FakeClient()
    result = actions.autosync(client=fake)
    assert result["weeks"] == [2, 3, 4]
    assert fake.pushed_weeks == [["current tue", "current sat"], ["next tue"], ["later tue"]]


def test_deletes_stale_completed_ids_and_clears_them():
    store.save_plan(_plan())
    fake = _FakeClient()
    result = actions.autosync(client=fake)
    assert result["stale_deleted"] == 1
    assert fake.deleted == [77]
    saved = store.load_plan()
    assert saved.weeks[0].workouts[0].garmin_workout_id is None


def test_second_run_is_idempotent():
    store.save_plan(_plan())
    actions.autosync(client=_FakeClient())
    fake2 = _FakeClient()
    result = actions.autosync(client=fake2)
    assert result["stale_deleted"] == 0  # stale id already cleared on run 1
    assert result["weeks"] == [2, 3, 4]
    assert fake2.pushed_weeks == [["current tue", "current sat"], ["next tue"], ["later tue"]]


def test_unaccepted_plan_refuses():
    store.save_plan(_plan(accepted=False))
    with pytest.raises(RuntimeError, match="not accepted"):
        actions.autosync(client=_FakeClient())
