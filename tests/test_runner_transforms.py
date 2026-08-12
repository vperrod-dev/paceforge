"""The save-* transforms ported from workflow inline Python into scripts/runner.py."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from runner import (  # noqa: E402
    append_ride,
    patch_bike_profile,
    pending_analyses,
    planned_session,
    upsert_rpe,
    write_benchmarks,
    write_events,
)


def read(p: Path) -> dict:
    return json.loads(p.read_text())


def test_upsert_rpe_appends_clean_entry(tmp_path):
    upsert_rpe({"activity_id": 7, "date": "2026-07-21", "rpe": 8, "duration_min": 40}, tmp_path)
    assert read(tmp_path / "rpe.json")["entries"][0]["rpe"] == 8


def test_upsert_rpe_replaces_same_activity(tmp_path):
    upsert_rpe({"activity_id": 7, "date": "2026-07-21", "rpe": 5}, tmp_path)
    upsert_rpe({"activity_id": 7, "date": "2026-07-21", "rpe": 9}, tmp_path)
    assert [e["rpe"] for e in read(tmp_path / "rpe.json")["entries"]] == [9]


def test_upsert_rpe_rejects_out_of_range(tmp_path):
    with pytest.raises(ValueError):
        upsert_rpe({"activity_id": 7, "date": "2026-07-21", "rpe": 11}, tmp_path)


def test_append_ride_is_idempotent_on_date(tmp_path):
    append_ride({"date": "2026-07-21T18:00:00", "duration_sec": 3600, "tss": 60}, tmp_path)
    append_ride({"date": "2026-07-21T18:00:00", "duration_sec": 3600, "tss": 65}, tmp_path)
    assert [r["tss"] for r in read(tmp_path / "bike" / "rides.json")["rides"]] == [65.0]


def test_append_ride_requires_duration(tmp_path):
    with pytest.raises(ValueError):
        append_ride({"date": "2026-07-21T18:00:00"}, tmp_path)


def test_append_ride_keeps_valid_trace_points_only(tmp_path):
    trace = [[0, 150, 120], [5, 210, None], ["bad"], [10, 9999, 100], [15, 180, 999]]
    append_ride({"date": "2026-07-21T18:00:00", "duration_sec": 3600, "trace": trace}, tmp_path)
    ride = read(tmp_path / "bike" / "rides.json")["rides"][0]
    assert ride["trace"] == [[0, 150, 120], [5, 210, None], [15, 180, None]]


def test_append_ride_omits_trace_key_when_absent(tmp_path):
    append_ride({"date": "2026-07-21T18:00:00", "duration_sec": 3600}, tmp_path)
    assert "trace" not in read(tmp_path / "bike" / "rides.json")["rides"][0]


def test_append_ride_rejects_out_of_range_ftp(tmp_path):
    with pytest.raises(ValueError):
        append_ride({"date": "2026-07-21T18:00:00", "duration_sec": 3600, "ftp": 5000}, tmp_path)


def test_bike_profile_rejects_out_of_range_ftp(tmp_path):
    with pytest.raises(ValueError):
        patch_bike_profile({"ftp": 9000}, tmp_path, today="2026-07-21")


def test_bike_profile_ftp_change_grows_history(tmp_path):
    patch_bike_profile({"ftp": 250}, tmp_path, today="2026-07-21")
    patch_bike_profile({"ftp": 260}, tmp_path, today="2026-07-22")
    assert [h["ftp"] for h in read(tmp_path / "bike" / "profile.json")["ftp_history"]] == [250, 260]


def test_bike_profile_same_ftp_no_history_entry(tmp_path):
    patch_bike_profile({"ftp": 250}, tmp_path, today="2026-07-21")
    patch_bike_profile({"ftp": 250}, tmp_path, today="2026-07-22")
    assert len(read(tmp_path / "bike" / "profile.json")["ftp_history"]) == 1


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_pending_analyses_covers_unplanned_activities_and_bike_rides(tmp_path):
    (tmp_path / "analyses").mkdir()
    (tmp_path / "analyses" / "2.md").write_text("done")
    (tmp_path / "activities.json").write_text(json.dumps([
        {"activity_id": 1, "start_time": "2026-07-27T07:00:00", "activity_type": "running"},
        {"activity_id": 2, "start_time": "2026-07-26T07:00:00", "activity_type": "indoor_cardio"},
        {"activity_id": 3, "start_time": "2026-05-01T07:00:00", "activity_type": "running"},
    ]))
    (tmp_path / "bike").mkdir()
    (tmp_path / "bike" / "rides.json").write_text(json.dumps({"rides": [
        {"date": "2026-07-27T17:10:04", "duration_sec": 3600},
    ]}))
    assert pending_analyses(tmp_path, now=NOW) == ["bike:2026-07-27T17:10:04", "1"]


def test_pending_analyses_caps_batch_newest_first(tmp_path):
    (tmp_path / "activities.json").write_text(json.dumps([
        {"activity_id": i, "start_time": f"2026-07-{10 + i:02d}T07:00:00"} for i in range(1, 15)
    ]))
    ids = pending_analyses(tmp_path, now=NOW)
    assert len(ids) == 10
    assert ids[0] == "14"


def test_pending_analyses_survives_missing_files(tmp_path):
    assert pending_analyses(tmp_path, now=NOW) == []


def test_write_events_accepts_a_list(tmp_path):
    write_events([{"name": "Dublin Marathon"}], tmp_path)
    assert read(tmp_path / "events.json") == [{"name": "Dublin Marathon"}]


def test_write_events_rejects_non_list(tmp_path):
    with pytest.raises(ValueError):
        write_events({"name": "Dublin Marathon"}, tmp_path)


def test_write_benchmarks_accepts_a_dict(tmp_path):
    write_benchmarks({"deadlift_kg": 180}, tmp_path)
    assert read(tmp_path / "benchmarks.json") == {"deadlift_kg": 180}


def test_write_benchmarks_rejects_non_dict(tmp_path):
    with pytest.raises(ValueError):
        write_benchmarks([180], tmp_path)


def _plan_file(tmp_path, matched):
    (tmp_path / "plan.json").write_text(json.dumps({"weeks": [{"workouts": [
        {"name": "4km Tempo Run", "session_id": "4aee9725", "workout_type": "tempo",
         "scheduled_date": "2026-08-12", "matched_activity_ids": matched},
    ]}]}))


def _calendar_file(tmp_path, matched):
    (tmp_path / "calendar.json").write_text(json.dumps([
        {"item_id": "0589c109", "date": "2026-08-11", "sport": "Cardio", "title": "Un1t",
         "duration_min": 45, "matched_activity_ids": matched, "completed": bool(matched)},
    ]))


def test_planned_session_names_the_plan_workout(tmp_path):
    _plan_file(tmp_path, [23948272738])
    _calendar_file(tmp_path, [])
    assert "plan workout \"4km Tempo Run\"" in planned_session(tmp_path, "23948272738")


def test_planned_session_names_the_calendar_item(tmp_path):
    _plan_file(tmp_path, [])
    _calendar_file(tmp_path, ["23931390221"])
    line = planned_session(tmp_path, "23931390221")
    assert line.startswith("PLANNED") and 'calendar item "Un1t"' in line


def test_planned_session_reports_unplanned_when_nothing_claims_it(tmp_path):
    _plan_file(tmp_path, [])
    _calendar_file(tmp_path, [])
    assert planned_session(tmp_path, "999").startswith("UNPLANNED")
