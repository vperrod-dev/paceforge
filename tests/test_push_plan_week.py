"""push_plan_week()/push_workout() dedup + sport fallback, mocked at the Garmin API boundary."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge.garmin.client import GarminClient
from paceforge.models.plan import Workout, WorkoutType


class _FakeGarmin:
    """garminconnect.Garmin stand-in recording every API call."""

    def __init__(self, reject_sports=None, reject_names=None, library=None):
        self.calls: list[tuple] = []
        self.reject_sports = reject_sports or set()
        self.reject_names = reject_names or set()
        self.library = library or []
        self._next_id = 500

    def delete_workout(self, workout_id):  # noqa: ANN001
        self.calls.append(("delete", int(workout_id)))

    def upload_running_workout(self, gw):  # noqa: ANN001
        sport = gw.sportType["sportTypeKey"]
        name = gw.workoutName
        self.calls.append(("upload", name, sport))
        if sport in self.reject_sports or name in self.reject_names:
            raise RuntimeError("upload rejected")
        self._next_id += 1
        return {"workoutId": self._next_id}

    def schedule_workout(self, workout_id, date_str):  # noqa: ANN001
        self.calls.append(("schedule", workout_id, date_str))

    def get_workouts(self, start=0, limit=200):  # noqa: ANN001
        if start == 0:
            return self.library
        return []


class _FailDeleteGarmin(_FakeGarmin):
    def __init__(self, *args, fail_delete_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_delete_ids = fail_delete_ids or set()

    def delete_workout(self, workout_id):  # noqa: ANN001
        # Record the attempt before failing — the real API call is observable
        # even when it fails, and callers are tested on seeing the attempt.
        self.calls.append(("delete", int(workout_id)))
        if int(workout_id) in self.fail_delete_ids:
            raise RuntimeError("garmin down")


def _client(fake: _FakeGarmin) -> GarminClient:
    client = GarminClient(email="a@example.com", password="x")
    client._client = fake
    return client


def _workout(name: str = "Easy 6k", wtype: WorkoutType = WorkoutType.EASY_RUN, **kwargs) -> Workout:
    return Workout(workout_type=wtype, name=name,
                   scheduled_date=date.today() + timedelta(days=1),
                   estimated_distance_meters=6000, **kwargs)


# ── dedup ─────────────────────────────────────────────────────────


def test_repush_deletes_stored_garmin_copy_before_uploading():
    fake = _FakeGarmin()
    _client(fake).push_plan_week([_workout(garmin_workout_id=42)])
    assert fake.calls[0] == ("delete", 42)


def test_first_push_of_untracked_workout_deletes_nothing():
    fake = _FakeGarmin()
    _client(fake).push_plan_week([_workout()])
    assert [c for c in fake.calls if c[0] == "delete"] == []


def test_untracked_duplicate_found_by_name_and_date_is_deleted():
    dup_date = (date.today() + timedelta(days=1)).isoformat()
    fake = _FakeGarmin(library=[{"workoutId": 99, "workoutName": "Easy 6k",
                                 "calendarDate": dup_date}])
    _client(fake).push_plan_week([_workout()])
    assert ("delete", 99) in fake.calls


def test_same_name_outside_week_dates_is_kept():
    far_away = (date.today() + timedelta(days=40)).isoformat()
    fake = _FakeGarmin(library=[{"workoutId": 99, "workoutName": "Easy 6k",
                                 "calendarDate": far_away}])
    _client(fake).push_plan_week([_workout()])
    assert ("delete", 99) not in fake.calls


# ── dedup-by-id ────────────────────────────────────────────────────


def test_all_new_ids_are_pushed_once():
    fake = _FakeGarmin()
    workouts = [_workout("New A"), _workout("New B")]
    _client(fake).push_plan_week(workouts)
    assert sorted(c for c in fake.calls if c[0] == "upload") == [
        ("upload", "New A", "running"),
        ("upload", "New B", "running"),
    ]
    for w in workouts:
        assert w.garmin_workout_id is not None


def test_push_stamps_new_garmin_id_on_workout():
    workout = _workout()
    _client(_FakeGarmin()).push_plan_week([workout])
    assert workout.garmin_workout_id == 501


def test_rest_workouts_are_never_pushed():
    fake = _FakeGarmin()
    result = _client(fake).push_plan_week([Workout(workout_type=WorkoutType.REST, name="Rest")])
    assert (result, fake.calls) == ({"pushed": [], "failed": []}, [])


def test_one_failed_upload_does_not_abort_the_week():
    fake = _FakeGarmin(reject_names={"Easy 6k"})
    result = _client(fake).push_plan_week([_workout("Easy 6k"), _workout("Tempo 8k")])
    assert ([f["name"] for f in result["failed"]],
            [p["name"] for p in result["pushed"]]) == (["Easy 6k"], ["Tempo 8k"])


# ── sport selection + fallback ────────────────────────────────────


def test_hyrox_uploads_as_fitness_equipment():
    result = _client(_FakeGarmin()).push_workout(_workout(wtype=WorkoutType.HYROX_MIXED))
    assert result["sport_used"] == "fitness_equipment"


def test_bike_uploads_as_cycling():
    result = _client(_FakeGarmin()).push_workout(_workout(sport="bike"))
    assert result["sport_used"] == "cycling"


def test_rejected_fitness_equipment_falls_back_to_running():
    fake = _FakeGarmin(reject_sports={"fitness_equipment"})
    result = _client(fake).push_workout(_workout(wtype=WorkoutType.HYROX_MIXED))
    assert result["sport_used"] == "running"


def test_rejected_running_upload_raises_without_retry():
    fake = _FakeGarmin(reject_sports={"running"})
    with pytest.raises(RuntimeError):
        _client(fake).push_workout(_workout())
    assert [c for c in fake.calls if c[0] == "upload"] == [("upload", "Easy 6k", "running")]


def test_push_workout_schedules_on_the_given_date():
    fake = _FakeGarmin()
    when = date.today() + timedelta(days=3)
    _client(fake).push_workout(_workout(), schedule_date=when)
    assert ("schedule", 501, when.isoformat()) in fake.calls


# ── failed delete regression ───────────────────────────────────────


def test_push_plan_week_keeps_id_when_delete_fails():
    workouts = [_workout("Keep", garmin_workout_id=42)]
    fake = _FailDeleteGarmin(fail_delete_ids={42})
    result = _client(fake).push_plan_week(workouts)

    assert workouts[0].garmin_workout_id == 42
    assert ("delete", 42) in fake.calls
    assert [f["name"] for f in result["failed"]] == ["Keep"]
    assert result["pushed"] == []


def test_push_plan_week_reports_delete_failure():
    fake = _FailDeleteGarmin(fail_delete_ids={42})
    workouts = [_workout("Keep", garmin_workout_id=42)]
    result = _client(fake).push_plan_week(workouts)

    assert result["failed"][0]["name"] == "Keep"
    assert "RuntimeError" in result["failed"][0]["error"]


def test_push_plan_week_skips_upload_after_failed_delete():
    fake = _FailDeleteGarmin(fail_delete_ids={42})
    workouts = [_workout("Keep", garmin_workout_id=42)]
    _client(fake).push_plan_week(workouts)

    assert [c for c in fake.calls if c[0] == "upload"] == []


def test_push_plan_week_mixed_delete_failure_continues_with_uploadable():
    fake = _FailDeleteGarmin(fail_delete_ids={42})
    workouts = [
        _workout("FailDelete", garmin_workout_id=42),
        _workout("Fresh"),
    ]
    result = _client(fake).push_plan_week(workouts)

    assert workouts[0].garmin_workout_id == 42
    assert workouts[1].garmin_workout_id is not None
    assert [f["name"] for f in result["failed"]] == ["FailDelete"]
    assert [p["name"] for p in result["pushed"]] == ["Fresh"]
