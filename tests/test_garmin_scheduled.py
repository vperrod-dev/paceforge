"""get_scheduled_workouts() caps the per-day fallback instead of one call per day."""

from __future__ import annotations

from paceforge.garmin.client import GarminClient


class _FakeGarmin:
    """Garmin API stub where methods 1 and 2 yield nothing, forcing the day loop."""

    def __init__(self):
        self.day_calls = 0

    def connectapi(self, path):  # noqa: ANN001
        raise RuntimeError("calendar-service down")

    def get_workouts(self, start=0, limit=200):  # noqa: ANN001
        return []

    def get_all_day_events(self, cdate):  # noqa: ANN001
        self.day_calls += 1
        return []


def _client() -> GarminClient:
    client = GarminClient(email="a@example.com", password="x")
    client._client = _FakeGarmin()
    return client


def test_day_fallback_capped_at_60_calls():
    client = _client()
    client.get_scheduled_workouts(days_ahead=400)
    assert client._client.day_calls == 60


def test_day_fallback_respects_smaller_days_ahead():
    client = _client()
    client.get_scheduled_workouts(days_ahead=7)
    assert client._client.day_calls == 7


def test_day_fallback_stops_on_rate_limit():
    class _RateLimited(_FakeGarmin):
        def get_all_day_events(self, cdate):  # noqa: ANN001
            self.day_calls += 1
            raise RuntimeError("429 Client Error: Too Many Requests")

    client = _client()
    client._client = _RateLimited()
    client.get_scheduled_workouts(days_ahead=400)
    assert client._client.day_calls == 1


def test_day_fallback_paces_between_calls(monkeypatch):
    from paceforge.garmin import client as garmin_client

    sleeps: list[float] = []
    monkeypatch.setattr(garmin_client, "READ_PACE_SECONDS", 0.5)
    monkeypatch.setattr(garmin_client.time, "sleep", sleeps.append)
    client = _client()
    client.get_scheduled_workouts(days_ahead=3)
    assert sleeps == [0.5, 0.5]
