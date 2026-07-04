"""Daily wellness history storage (the time-series trend metrics depend on)."""
import json

import pytest

from paceforge import store
from paceforge.engine.analytics import _normalize_lt_speed
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _profile(date, **kw):
    return UserFitnessProfile(profile_date=date, **kw)


def test_append_then_load_roundtrip():
    store.append_daily_history(_profile("2026-06-01", vo2_max=55.0, resting_hr=46))
    rows = store.load_history()
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01" and rows[0]["vo2_max"] == 55.0


def test_upsert_replaces_same_day():
    store.append_daily_history(_profile("2026-06-01", resting_hr=46))
    store.append_daily_history(_profile("2026-06-01", resting_hr=50))
    rows = store.load_history()
    assert len(rows) == 1 and rows[0]["resting_hr"] == 50


def test_keeps_distinct_days_sorted():
    store.append_daily_history(_profile("2026-06-03", resting_hr=46))
    store.append_daily_history(_profile("2026-06-01", resting_hr=46))
    store.append_daily_history(_profile("2026-06-02", resting_hr=46))
    assert [r["date"] for r in store.load_history()] == ["2026-06-01", "2026-06-02", "2026-06-03"]


def test_load_empty_when_absent():
    assert store.load_history() == []


def test_no_date_is_ignored():
    result = store.append_daily_history(UserFitnessProfile.model_construct(profile_date=None))
    assert store.load_history() == []
    assert result == {"written": False, "reason": "no_profile_date"}


def test_all_null_snapshot_is_skipped():
    # A failed wellness fetch yields a profile with only a date — no history row.
    result = store.append_daily_history(_profile("2026-06-29"))
    assert result == {"written": False, "reason": "skipped_all_null"}
    assert store.load_history() == []


def test_activity_only_snapshot_is_still_skipped():
    # max_hr / weekly mileage derive from activities, so they survive a failed
    # wellness fetch — a row carrying only those is still a failed sync.
    result = store.append_daily_history(_profile("2026-06-29", max_hr=195, weekly_mileage_km=13.4))
    assert result == {"written": False, "reason": "skipped_all_null"}
    assert store.load_history() == []


def test_partial_snapshot_merges_with_existing_row():
    store.append_daily_history(_profile("2026-06-01", vo2_max=55.0, resting_hr=46))
    store.append_daily_history(_profile("2026-06-01", resting_hr=50))  # re-sync, vo2 fetch failed
    rows = store.load_history()
    assert len(rows) == 1
    assert rows[0]["resting_hr"] == 50  # fresh value wins
    assert rows[0]["vo2_max"] == 55.0  # null did not erase the morning's value


def test_repair_drops_all_null_rows_and_merges_duplicates():
    good = {"date": "2026-06-27", "vo2_max": 55.0}
    # The failed-sync shape: every wellness field null, only activity-derived values set.
    bad = {"date": "2026-06-29", "max_hr": 195, "weekly_mileage_km": 13.4}
    dupe_a = {"date": "2026-06-30", "vo2_max": 55.5}
    dupe_b = {"date": "2026-06-30", "resting_hr": 46}
    lines = [json.dumps({**{f: None for f in store._HISTORY_FIELDS}, **r}) for r in
             (good, bad, dupe_a, dupe_b)]
    store._write(store._path("history.jsonl"), "\n".join(lines) + "\n")

    result = store.repair_history()

    assert result == {"kept": 2, "dropped": 1}
    rows = store.load_history()
    assert [r["date"] for r in rows] == ["2026-06-27", "2026-06-30"]
    merged = rows[1]
    assert merged["vo2_max"] == 55.5 and merged["resting_hr"] == 46


def test_lt_speed_normalizes_the_tenths_bug():
    # Garmin returned 0.386 — really 3.86 m/s (4:19/km). The fix multiplies by 10.
    assert round(_normalize_lt_speed(0.38611003), 2) == 3.86
    assert _normalize_lt_speed(3.86) == 3.86  # already-normalized is idempotent
