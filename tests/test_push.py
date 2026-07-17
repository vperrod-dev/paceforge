"""push() validate-gates before touching Garmin and persists garmin_workout_id for dedup."""

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
        self.pushed: list[Workout] = []
        self.incoming_ids: list[int | None] = []  # garmin_workout_id as received per call
        self._next_id = 1000

    def push_plan_week(self, workouts, plan_paces=None, pace_bands=None):  # noqa: ANN001
        self.pushed.extend(workouts)
        self.incoming_ids.extend(w.garmin_workout_id for w in workouts)
        for w in workouts:
            self._next_id += 1
            w.garmin_workout_id = self._next_id
        return {"pushed": [{"name": w.name} for w in workouts], "failed": []}


@pytest.fixture()
def fake_client(monkeypatch) -> _FakeClient:
    fake = _FakeClient()
    monkeypatch.setattr(actions, "garmin_connect", lambda: fake)
    return fake


def _workout(name: str, day_offset: int, wtype: WorkoutType = WorkoutType.EASY_RUN) -> Workout:
    return Workout(workout_type=wtype, name=name,
                   scheduled_date=date.today() + timedelta(days=day_offset))


def _plan(workouts: list[Workout]) -> TrainingPlan:
    return TrainingPlan(
        name="test", goal_type="MARATHON", target_date=date.today() + timedelta(days=60),
        total_weeks=1, accepted=True,
        weeks=[TrainingWeek(week_number=1, workouts=workouts)],
    )


def test_invalid_plan_never_reaches_garmin(fake_client):
    # Two intense sessions on consecutive days fails validation.
    store.save_plan(_plan([_workout("tempo tue", 1, WorkoutType.TEMPO),
                           _workout("intervals wed", 2, WorkoutType.INTERVALS)]))
    with pytest.raises(RuntimeError, match="failed validation"):
        actions.push(week=1)
    assert fake_client.pushed == []


def test_dry_run_never_reaches_garmin(fake_client):
    store.save_plan(_plan([_workout("easy tue", 1)]))
    result = actions.push(week=1, dry_run=True)
    assert result["dry_run"] is True
    assert fake_client.pushed == []


def test_push_persists_garmin_workout_id(fake_client):
    store.save_plan(_plan([_workout("easy tue", 1)]))
    result = actions.push(week=1)
    assert result["pushed"] == 1
    saved = store.load_plan()
    assert saved.weeks[0].workouts[0].garmin_workout_id == 1001


def test_repush_hands_stored_id_to_client_for_dedup(fake_client):
    store.save_plan(_plan([_workout("easy tue", 1)]))
    actions.push(week=1)
    actions.push(week=1)
    # Second push must carry the persisted id so push_plan_week can delete-by-id.
    assert fake_client.incoming_ids == [None, 1001]


def test_autosync_persists_new_garmin_ids(fake_client):
    store.save_plan(_plan([_workout("easy tue", 1)]))
    actions.autosync(client=fake_client)
    saved = store.load_plan()
    assert saved.weeks[0].workouts[0].garmin_workout_id == 1001
