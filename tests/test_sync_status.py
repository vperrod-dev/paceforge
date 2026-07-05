"""sync() must always leave a truthful data/sync-status.json behind."""
import pytest

from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


class _FakeClient:
    def __init__(self, profile, endpoint_report):
        self._profile = profile
        self.endpoint_report = {}
        self._report = endpoint_report

    def get_fitness_profile(self, lookback_days=90):
        self.endpoint_report = dict(self._report)
        return self._profile

    def dump_tokens(self, token_dir):
        pass


def _run_sync(monkeypatch, client):
    monkeypatch.setattr(actions, "garmin_connect", lambda: client)
    monkeypatch.setattr(actions, "_sync_details", lambda c, limit=40: (0, 0))
    return actions.sync()


def test_clean_sync_writes_ok_status(monkeypatch):
    profile = UserFitnessProfile(profile_date="2026-07-04", vo2_max=54.7, resting_hr=50)
    client = _FakeClient(profile, {"hrv": {"ok": True}, "sleep": {"ok": True}})

    result = _run_sync(monkeypatch, client)

    assert result["result"] == "ok" and result["failed_endpoints"] == []
    status = store.load_sync_status()
    assert status["result"] == "ok"
    assert status["last_success"] == status["last_attempt"]
    assert status["counters"]["history_written"] is True


def test_endpoint_failure_marks_partial(monkeypatch):
    profile = UserFitnessProfile(profile_date="2026-07-04", vo2_max=54.7)
    client = _FakeClient(profile, {
        "hrv": {"ok": False, "error": "HTTPError: 500"},
        "sleep": {"ok": True},
    })

    result = _run_sync(monkeypatch, client)

    assert result["result"] == "partial" and result["failed_endpoints"] == ["hrv"]
    status = store.load_sync_status()
    assert status["result"] == "partial"
    assert status["endpoints"]["hrv"]["ok"] is False
    assert status["last_success"] is not None  # partial still counts as a landing


def test_all_null_wellness_marks_partial(monkeypatch):
    # Endpoints "succeed" (empty 200s) but nothing came back — history skips the row.
    profile = UserFitnessProfile(profile_date="2026-07-04")
    client = _FakeClient(profile, {"hrv": {"ok": True}})

    result = _run_sync(monkeypatch, client)

    assert result["result"] == "partial"
    status = store.load_sync_status()
    assert status["counters"]["history_skip_reason"] == "skipped_all_null"


def test_hard_failure_still_writes_status(monkeypatch):
    def _boom():
        raise RuntimeError("No valid Garmin token — run `paceforge login` once.")

    monkeypatch.setattr(actions, "garmin_connect", _boom)

    with pytest.raises(RuntimeError):
        actions.sync()

    status = store.load_sync_status()
    assert status["result"] == "failed"
    assert "No valid Garmin token" in status["error"]
    assert status["last_success"] is None


def test_failure_preserves_previous_last_success(monkeypatch):
    profile = UserFitnessProfile(profile_date="2026-07-04", vo2_max=54.7)
    _run_sync(monkeypatch, _FakeClient(profile, {}))
    first_success = store.load_sync_status()["last_success"]

    monkeypatch.setattr(actions, "garmin_connect",
                        lambda: (_ for _ in ()).throw(RuntimeError("Garmin down")))
    with pytest.raises(RuntimeError):
        actions.sync()

    status = store.load_sync_status()
    assert status["result"] == "failed"
    assert status["last_success"] == first_success
