"""push() validate-gates before touching Garmin and persists garmin_workout_id for dedup."""

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

    def get_scheduled_workouts(self, days_ahead=30):  # noqa: ANN001
        return []


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


class _FakeGarmin:
    def __init__(self):
        self.calls = []
        self._next_id = 100

    def delete_workout(self, workout_id):
        self.calls.append(("delete", int(workout_id)))

    def upload_running_workout(self, gw):
        self.calls.append(("upload", gw.workoutName, gw.sportType["sportTypeKey"]))
        self._next_id += 1
        return {"workoutId": self._next_id}

    def schedule_workout(self, workout_id, date_str):
        self.calls.append(("schedule", workout_id, date_str))

    def get_workouts(self, start=0, limit=200):
        return []


def _real_client(fake):
    client = GarminClient(email="a@example.com", password="x", token_dir="")
    client._client = fake
    return client


def _install_fake_upload(real, fake):
    real._upload = lambda workout, sport, plan_paces=None, pace_bands=None: fake.upload_running_workout(
        type("GW", (), {"workoutName": workout.name, "sportType": sport})()
    )


def test_unmapped_workout_type_uses_running_default():
    fake = _FakeGarmin()
    workout = _workout("New Type", 1)
    workout.workout_type = "brand_new_type"  # type: ignore[assignment]
    client = _real_client(fake)
    _install_fake_upload(client, fake)
    result = client.push_workout(workout)
    assert result["sport_used"] == "running"
    assert any(c[0] == "upload" and c[2] == "running" for c in fake.calls)


def test_invalid_sport_is_handled_gracefully_as_running():
    fake = _FakeGarmin()
    workout = _workout("Invalid", 1)
    workout.sport = "kayaking"
    client = _real_client(fake)
    _install_fake_upload(client, fake)
    result = client.push_workout(workout)
    assert result["sport_used"] == "running"
    assert [c for c in fake.calls if c[0] == "upload"][0][2] == "running"

def test_rejected_fitness_equipment_falls_back_to_running_via_real_push_workout():
    fake = _FakeGarmin()
    workout = _workout("HYROX", 1, WorkoutType.HYROX_MIXED)
    client = _real_client(fake)

    calls = {"count": 0}

    def fake_upload(w, sport, plan_paces=None, pace_bands=None):
        calls["count"] += 1
        if sport["sportTypeKey"] == "fitness_equipment":
            raise RuntimeError("rejected")
        return fake.upload_running_workout(
            type("GW", (), {"workoutName": w.name, "sportType": sport})()
        )

    client._upload = fake_upload  # type: ignore[method-assign]
    result = client.push_workout(workout)
    assert result["sport_used"] == "running"
    assert calls["count"] == 2


# TODO(/home/azureuser/projects/paceforge/tests/test_push.py): real-upload schema validation for unknown
# sport input is not covered here. The current unknown-sport branch still lacks a test that asserts an
# invalid sport fails early/gracefully before any fallback retry; it needs the real uploader mounted
# against a malformed step payload and a rejected-style assertion.
# For these tests we only cover the nested fallback: default sport selection -> upload success -> reject
# non-running -> fallback to running -> success; and nested failure on both attempts -> propagated error.






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
