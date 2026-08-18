"""save-ride writes rides.json, then links the ride to a same-day calendar item.

The link (actions._match_plan) runs outside the write lock, after rides.json is
already on disk, so a ride that lands in rides.json but never gets linked would
leave the planned Bike item showing as not done — this is the regression this
test guards.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402

from paceforge import store  # noqa: E402
from paceforge.models.calendar import ScheduledItem  # noqa: E402


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data" / "bike").mkdir(parents=True)
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return tmp_path / "data"


@pytest.fixture
def calls(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(runner, "commit_push", lambda run, paths, msg: seen.update(paths=paths))
    monkeypatch.setattr(runner, "publish", lambda run: None)
    return seen


def _save(entry):
    run = runner.Run("save-ride")
    runner.job_save_ride(run, {"data": entry})
    return run


def test_a_saved_ride_links_to_a_same_day_bike_item(data, calls):
    today = date.today()
    item = ScheduledItem(date=today, sport="Bike", title="Zwift ride", duration_min=45)
    store.save_calendar([item])

    _save({"date": f"{today.isoformat()}T07:00:00", "workout": "Morning ride",
           "duration_sec": 1800})

    [saved] = store.load_calendar()
    assert saved.matched_activity_ids == [f"bike:{today.isoformat()}T07:00:00"]
    assert saved.completed is True


def test_all_three_files_land_in_the_commit(data, calls):
    today = date.today()
    store.save_calendar([ScheduledItem(date=today, sport="Bike", title="Zwift ride")])

    _save({"date": f"{today.isoformat()}T07:00:00", "workout": "Morning ride",
           "duration_sec": 1800})

    assert calls["paths"] == ["data/bike/rides.json", "data/calendar.json", "data/plan.json"]


def test_the_job_is_registered_for_dispatch():
    assert runner.JOBS["save-ride"] is runner.job_save_ride
