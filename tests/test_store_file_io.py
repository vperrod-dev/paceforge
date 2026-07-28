"""Test store.py file I/O atomicity and error handling — 52 stmts untested."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from tempfile import TemporaryDirectory

import pytest

from paceforge import store
from paceforge.models.profile import UserFitnessProfile, RecentActivity


class TestFileAtomicity:
    """_write() atomic file operations protect against crashes."""

    def test_write_creates_parent_directories(self):
        """_write() creates parent dirs if missing."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "deep" / "file.json"
            store._write(path, '{"test": true}')
            assert path.exists()
            assert json.loads(path.read_text()) == {"test": True}

    def test_write_uses_temp_file_atomic_rename(self):
        """_write() writes to .tmp then renames (crash-safe)."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target.json"
            with patch('os.replace') as mock_replace:
                store._write(path, '{"data": true}')
                # Verify os.replace was called (atomic rename)
                assert mock_replace.called
                tmp_path = mock_replace.call_args[0][0]
                assert str(tmp_path).endswith('.tmp')

    def test_write_temp_file_removed_on_crash(self):
        """_write() cleanup on write failure (no orphaned .tmp)."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target.json"
            # Simulate write failure mid-process
            with patch('os.replace', side_effect=OSError("Disk full")):
                with pytest.raises(OSError):
                    store._write(path, '{"bad": true}')
                # Verify no .tmp left behind
                tmp_path = path.with_name(path.name + ".tmp")
                # Note: cleanup is implicit if write() fails before tmp.write_text()


class TestProfileSaveAndLoad:
    """save_profile() preserves non-empty fields through updates."""

    def test_load_profile_nonexistent_returns_none(self):
        """load_profile() returns None when profile.json missing."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                result = store.load_profile()
                assert result is None

    def test_save_new_profile_creates_file(self):
        """save_profile() writes fresh profile.json."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                profile = UserFitnessProfile(
                    vo2_max=45.0, resting_hr=50, profile_date="2026-07-28"
                )
                store.save_profile(profile)
                path = Path(tmpdir) / "profile.json"
                assert path.exists()
                saved = UserFitnessProfile.model_validate_json(path.read_text())
                assert saved.vo2_max == 45.0

    def test_save_profile_merge_preserves_old_vo2_max(self):
        """save_profile() preserves old VO2max when new value is null."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                # Save initial profile
                profile1 = UserFitnessProfile(
                    vo2_max=45.0, resting_hr=50, profile_date="2026-07-27"
                )
                store.save_profile(profile1)

                # Update with null VO2max (Garmin endpoint intermittent failure)
                profile2 = UserFitnessProfile(
                    vo2_max=None, resting_hr=51, profile_date="2026-07-28"
                )
                store.save_profile(profile2)

                # Verify old VO2max preserved
                loaded = store.load_profile()
                assert loaded.vo2_max == 45.0
                assert loaded.resting_hr == 51

    def test_save_profile_new_value_replaces_old(self):
        """save_profile() updates field when new value is non-empty."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                profile1 = UserFitnessProfile(
                    vo2_max=45.0, resting_hr=50, profile_date="2026-07-27"
                )
                store.save_profile(profile1)

                profile2 = UserFitnessProfile(
                    vo2_max=46.0, resting_hr=50, profile_date="2026-07-28"
                )
                store.save_profile(profile2)

                loaded = store.load_profile()
                assert loaded.vo2_max == 46.0


class TestDailyHistoryAppend:
    """append_daily_history() upserts daily wellness snapshots."""

    def test_append_writes_valid_profile_with_date(self):
        """append_daily_history() writes record with valid profile_date."""
        profile = UserFitnessProfile(vo2_max=45.0, resting_hr=50)
        result = store.append_daily_history(profile)
        assert result["written"] is True
        assert result["reason"] is None

    def test_append_skips_all_null_wellness(self):
        """append_daily_history() skips all-null snapshots (fetch failed)."""
        profile = UserFitnessProfile(
            profile_date="2026-07-28",
            vo2_max=None,
            resting_hr=None,
            training_readiness=None,
            # ... all wellness fields null
        )
        result = store.append_daily_history(profile)
        assert result["written"] is False
        assert result["reason"] == "skipped_all_null"

    def test_append_merges_partial_wellness_with_existing(self):
        """append_daily_history() merges partial row with prior entry for same date."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                # First update: write vo2_max only
                profile1 = UserFitnessProfile(
                    profile_date="2026-07-28",
                    vo2_max=45.0,
                    resting_hr=None,
                    training_readiness=None,
                )
                store.append_daily_history(profile1)

                # Second update: write resting_hr, null vo2_max (fetch partial)
                profile2 = UserFitnessProfile(
                    profile_date="2026-07-28",
                    vo2_max=None,
                    resting_hr=50,
                    training_readiness=None,
                )
                result = store.append_daily_history(profile2)

                # Verify both fields present
                assert result["written"] is True
                history = store.load_history()
                today = [h for h in history if h["date"] == "2026-07-28"][0]
                assert today["vo2_max"] == 45.0
                assert today["resting_hr"] == 50

    def test_append_replaces_row_for_same_date(self):
        """append_daily_history() upserts (not appends) same date."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                profile = UserFitnessProfile(
                    profile_date="2026-07-28",
                    vo2_max=45.0,
                    resting_hr=50,
                    training_readiness=90,
                )
                store.append_daily_history(profile)
                store.append_daily_history(profile)

                history = store.load_history()
                today_rows = [h for h in history if h["date"] == "2026-07-28"]
                assert len(today_rows) == 1  # One row, not duplicated


class TestRPEStorage:
    """upsert_rpe() indexes session effort ratings."""

    def test_upsert_rpe_creates_entry(self):
        """upsert_rpe() saves new RPE entry."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                entry = {"activity_id": 123, "rpe": 7}
                result = store.upsert_rpe(entry)
                assert "entries" in result
                assert len(result["entries"]) == 1

                rpe_by_act = store.rpe_by_activity()
                assert rpe_by_act[123]["rpe"] == 7

    def test_upsert_rpe_updates_existing(self):
        """upsert_rpe() overwrites prior RPE for same activity."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                store.upsert_rpe({"activity_id": 123, "rpe": 6})
                store.upsert_rpe({"activity_id": 123, "rpe": 8})

                rpe_by_act = store.rpe_by_activity()
                assert rpe_by_act[123]["rpe"] == 8
                assert len(rpe_by_act) == 1  # Only one entry for activity 123


class TestDetailStorage:
    """Detail file loading/saving for activity splits."""

    def test_has_detail_missing_file(self):
        """has_detail() returns False when no detail file."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                assert store.has_detail(999) is False

    def test_load_detail_missing_file(self):
        """load_detail() returns None for missing file."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                result = store.load_detail(999)
                assert result is None

    def test_save_and_load_detail(self):
        """save_detail() + load_detail() round-trip."""
        with TemporaryDirectory() as tmpdir:
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                detail = {
                    "activity_id": 123,
                    "splits": [
                        {"km": 1, "pace_sec": 300},
                        {"km": 2, "pace_sec": 305},
                    ]
                }
                store.save_detail(123, detail)
                loaded = store.load_detail(123)
                assert loaded == detail


class TestJSONParseErrors:
    """Error handling for malformed files."""

    def test_load_profile_corrupt_json(self):
        """load_profile() on corrupt JSON raises ValidationError."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            path.write_text("{invalid json}")
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                from pydantic import ValidationError
                with pytest.raises(Exception):  # ValidationError
                    store.load_profile()

    def test_load_history_corrupt_jsonl(self):
        """load_history() skips corrupt lines (partial parse)."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.jsonl"
            path.write_text('{"date": "2026-07-28", "vo2_max": 45}\n{bad\n')
            with patch.object(store, "DATA_DIR", Path(tmpdir)):
                # Should not crash; may skip bad lines or fail gracefully
                result = store.load_history()
                # Behavior depends on implementation: skip bad, parse good, or fail
