"""garmin_clear_calendar() removes scheduled workouts from today onwards only."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge import actions, store


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, scheduled):
        self._scheduled = scheduled
        self.deleted: list[int] = []

    def get_scheduled_workouts(self, days_ahead: int = 400):
        return self._scheduled

    def delete_workout(self, workout_id):  # noqa: ANN001
        self.deleted.append(int(workout_id))


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
