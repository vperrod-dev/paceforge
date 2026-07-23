"""The save-* transforms ported from workflow inline Python into scripts/runner.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from runner import (  # noqa: E402
    append_ride,
    patch_bike_profile,
    pending_analyses,
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


def test_pending_analyses_skips_existing_file(tmp_path):
    (tmp_path / "analyses").mkdir()
    (tmp_path / "analyses" / "2.md").write_text("done")
    (tmp_path / "plan.json").write_text(json.dumps({"weeks": [{"workouts": [
        {"completed": True, "matched_activity_ids": [1]},
        {"completed": True, "matched_activity_ids": [2]},
        {"completed": False, "matched_activity_ids": [3]},
    ]}]}))
    assert pending_analyses(tmp_path) == ["1"]


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
