"""calendar_edit() moves or removes one session and syncs it to Garmin."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, fail_ids: set[int] | None = None):
        self.deleted: list[int] = []
        self.pushed: list[str] = []
        self.fail_ids = fail_ids or set()

    def delete_workout(self, workout_id: int) -> bool:
        if workout_id in self.fail_ids:
            return False
        self.deleted.append(workout_id)
        return True

    def push_plan_week(self, workouts, plan_paces=None):  # noqa: ANN001
        for i, w in enumerate(workouts):
            if w.garmin_workout_id:
                self.deleted.append(w.garmin_workout_id)
            w.garmin_workout_id = 900 + i
            self.pushed.append(w.name)
        return {"pushed": self.pushed, "failed": []}


def _plan() -> TrainingPlan:
    ws = [
        Workout(
            workout_type=WorkoutType.EASY_RUN,
            name=f"w{i}",
            scheduled_date=date.today() + timedelta(days=i),
            garmin_workout_id=100 + i,
            estimated_distance_meters=6000,
        )
        for i in range(3)
    ]
    return TrainingPlan(
        name="P",
        goal_type="HALF_MARATHON",
        target_date=date.today() + timedelta(weeks=8),
        total_weeks=1,
        easy_pace=300.0,
        weeks=[TrainingWeek(week_number=1, total_distance_km=30, workouts=ws)],
    )


def test_calendar_edit_delete_removes_session_and_garmin_workout():
    plan = _plan()
    store.save_plan(plan)
    target = plan.weeks[0].workouts[0]
    sid, gid = target.session_id, target.garmin_workout_id
    fake = _FakeClient()

    result = actions.calendar_edit(sid, "delete", client=fake)

    assert result["action"] == "delete"
    assert gid in fake.deleted
    saved = store.load_plan()
    assert all(w.session_id != sid for wk in saved.weeks for w in wk.workouts)


def test_calendar_edit_delete_failure_raises_and_keeps_session():
    plan = _plan()
    store.save_plan(plan)
    target = plan.weeks[0].workouts[0]

    with pytest.raises(RuntimeError, match="session kept"):
        actions.calendar_edit(target.session_id, "delete",
                              client=_FakeClient(fail_ids={target.garmin_workout_id}))

    saved = store.load_plan()
    kept = next(w for wk in saved.weeks for w in wk.workouts if w.session_id == target.session_id)
    assert kept.garmin_workout_id == target.garmin_workout_id


def test_calendar_edit_reschedule_moves_date_and_repushes():
    plan = _plan()
    store.save_plan(plan)
    sid = plan.weeks[0].workouts[0].session_id
    new_date = (date.today() + timedelta(days=20)).isoformat()
    fake = _FakeClient()

    actions.calendar_edit(sid, "reschedule", new_date=new_date, client=fake)

    saved = store.load_plan()
    moved = next(w for wk in saved.weeks for w in wk.workouts if w.session_id == sid)
    assert str(moved.scheduled_date) == new_date
    assert moved.name in fake.pushed
