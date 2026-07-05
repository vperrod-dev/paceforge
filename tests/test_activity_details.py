"""Tests for the per-activity splits pipeline (store + sync_details + trim)."""

import pytest

from paceforge import actions, store
from paceforge.models.profile import RecentActivity


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _activity(activity_id: int) -> RecentActivity:
    return RecentActivity(
        activity_id=activity_id,
        name="run",
        activity_type="running",
        start_time=f"2026-06-{10 + activity_id:02d}T07:00:00",
        distance_meters=10000,
        duration_seconds=3000,
    )


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_activity_detail(self, activity_id):
        self.calls.append(activity_id)
        return {
            "activity_id": activity_id,
            "splits": {"lapDTOs": [
                {"distance": 1000, "duration": 300, "averageHR": 150, "maxHR": 160},
                {"distance": 1000, "duration": 290, "averageHR": 155, "maxHR": 162},
            ]},
        }


class TestTrimDetail:
    def test_per_lap_pace_is_seconds_per_km(self):
        out = actions._trim_detail({"activity_id": 7, "splits": {"lapDTOs": [
            {"distance": 1000, "duration": 300, "averageHR": 150}]}})
        assert out["splits"][0]["pace_sec"] == 300.0

    def test_keeps_lap_heart_rate(self):
        out = actions._trim_detail({"activity_id": 7, "splits": {"lapDTOs": [
            {"distance": 1000, "duration": 300, "averageHR": 150}]}})
        assert out["splits"][0]["avg_hr"] == 150


class TestStoreDetail:
    def test_save_then_load_roundtrips(self):
        store.save_detail(42, {"activity_id": 42, "splits": []})
        assert store.load_detail(42)["activity_id"] == 42

    def test_has_detail_false_when_absent(self):
        assert store.has_detail(999) is False


class TestSyncDetails:
    def test_fetches_each_recent_activity_once(self, monkeypatch):
        monkeypatch.setattr(actions.time, "sleep", lambda s: None)
        store.save_activities([_activity(1), _activity(2)])
        n, failed = actions._sync_details(FakeClient(), limit=40)
        assert n == 2 and failed == 0
        assert store.has_detail(1) and store.has_detail(2)

    def test_skips_activities_already_stored(self, monkeypatch):
        monkeypatch.setattr(actions.time, "sleep", lambda s: None)
        store.save_activities([_activity(1), _activity(2)])
        client = FakeClient()
        actions._sync_details(client, limit=40)
        client.calls.clear()
        again, _ = actions._sync_details(client, limit=40)
        assert again == 0
        assert client.calls == []


class TestExtractSeries:
    def _metrics(self, n, with_speed=True):
        descs = [{"key": "sumElapsedDuration", "metricsIndex": 0},
                 {"key": "directHeartRate", "metricsIndex": 1}]
        if with_speed:
            descs.append({"key": "directSpeed", "metricsIndex": 2})
        rows = [{"metrics": ([i * 5.0, 120 + (i % 20)] + ([3.0] if with_speed else []))}
                for i in range(n)]
        return {"metricDescriptors": descs, "activityDetailMetrics": rows}

    def test_downsamples_to_cap(self):
        s = actions._extract_series(self._metrics(400), max_points=120)
        assert 100 <= len(s) <= 120

    def test_run_has_hr_and_pace(self):
        s = actions._extract_series(self._metrics(50))
        assert s[0]["hr"] == 120 and s[0]["pace"] == round(1000 / 3.0, 1)

    def test_cardio_has_hr_no_pace(self):
        s = actions._extract_series(self._metrics(50, with_speed=False))
        assert s[0]["hr"] is not None and s[0]["pace"] is None

    def test_empty_or_missing_returns_none(self):
        assert actions._extract_series({}) is None
        assert actions._extract_series(None) is None
        assert actions._extract_series({"metricDescriptors": [], "activityDetailMetrics": []}) is None
