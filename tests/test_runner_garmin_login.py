"""The portal's Garmin sign-in state machine: garmin_login_start/garmin_mfa.

It handles the password/MFA handshake, the stale-tokenstore eviction and the
45-minute 429 retry loop from a background thread, mutating one shared GARMIN
dict the portal polls. None of that was covered — a regression here strands
the only way Victor can re-authenticate Garmin from the phone.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


class _FakeClient:
    """Stands in for GarminClient: login() returns or raises what a test wants."""

    def __init__(self, email, password, token_dir=None, results=None):
        self.email = email
        self.password = password
        self.token_dir = token_dir
        self._results = list(results or [])
        self.mfa_codes = []
        self._client = type(
            "_Inner", (), {"client": type("_Dump", (), {"dump": lambda self, d: None})()}
        )()

    def login(self):
        outcome = self._results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def complete_mfa(self, code):
        self.mfa_codes.append(code)


@pytest.fixture()
def garmin(monkeypatch, tmp_path):
    """Isolate the module globals the login thread mutates."""
    monkeypatch.setattr(runner, "GARMIN", dict(runner.GARMIN))
    monkeypatch.setattr(runner, "_GARMIN_CLIENT", None)
    monkeypatch.setenv("PACEFORGE_GARMIN_TOKEN_DIR", str(tmp_path / "tokens"))
    sent = []
    monkeypatch.setattr(runner, "telegram", lambda msg: sent.append(msg))
    finished = []
    monkeypatch.setattr(runner, "_garmin_finish", lambda: finished.append(True))
    monkeypatch.setattr(runner, "RETRY_EVERY", 0.01)
    monkeypatch.setattr(runner, "MAX_ATTEMPTS", 3)
    return type("G", (), {"sent": sent, "finished": finished, "tokens": tmp_path / "tokens"})


def _install_client(monkeypatch, results):
    """Patch the GarminClient the login thread imports at call time."""
    from paceforge.garmin import client as garmin_client

    made = []

    def factory(email, password, token_dir=None):
        made.append(_FakeClient(email, password, token_dir, results))
        return made[-1]

    monkeypatch.setattr(garmin_client, "GarminClient", factory)
    return made


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_successful_login_finishes_and_announces_it(monkeypatch, garmin):
    _install_client(monkeypatch, ["ok"])

    runner.garmin_login_start("victor@example.com", "secret")

    assert _wait_for(lambda: garmin.finished), runner.GARMIN
    assert any("connected" in msg for msg in garmin.sent)


def test_an_mfa_challenge_parks_the_state_machine_and_asks_for_the_code(monkeypatch, garmin):
    _install_client(monkeypatch, ["mfa_required"])

    runner.garmin_login_start("victor@example.com", "secret")

    assert _wait_for(lambda: runner.GARMIN["status"] == "pending_mfa")
    assert any("MFA" in msg for msg in garmin.sent)
    assert garmin.finished == []


def test_a_non_rate_limit_failure_stops_instead_of_retrying(monkeypatch, garmin):
    made = _install_client(monkeypatch, [RuntimeError("bad credentials")] * 3)

    runner.garmin_login_start("victor@example.com", "secret")

    assert _wait_for(lambda: runner.GARMIN["status"] == "error")
    assert "bad credentials" in runner.GARMIN["error"]
    assert len(made) == 1


def test_a_rate_limit_retries_up_to_max_attempts_then_gives_up(monkeypatch, garmin):
    made = _install_client(monkeypatch, [RuntimeError("HTTP 429 too many requests")] * 3)

    runner.garmin_login_start("victor@example.com", "secret")

    assert _wait_for(lambda: runner.GARMIN["status"] == "error")
    assert len(made) == 3
    assert "rate-limited" in runner.GARMIN["error"]


def test_a_stale_tokenstore_is_moved_aside_before_the_password_login(monkeypatch, garmin):
    garmin.tokens.mkdir(parents=True)
    (garmin.tokens / "garmin_tokens.json").write_text("stale", encoding="utf-8")
    _install_client(monkeypatch, ["ok"])

    runner.garmin_login_start("victor@example.com", "secret")

    assert _wait_for(lambda: garmin.finished)
    assert not (garmin.tokens / "garmin_tokens.json").exists()
    assert (garmin.tokens / "garmin_tokens.json.stale").read_text(encoding="utf-8") == "stale"


def test_the_mfa_code_reaches_the_pending_client(monkeypatch, garmin):
    made = _install_client(monkeypatch, ["mfa_required"])
    runner.garmin_login_start("victor@example.com", "secret")
    assert _wait_for(lambda: runner.GARMIN["status"] == "pending_mfa")

    runner.garmin_mfa("123456")

    assert _wait_for(lambda: garmin.finished)
    assert made[0].mfa_codes == ["123456"]


def test_an_mfa_code_with_no_login_in_progress_reports_an_error(garmin):
    runner.garmin_mfa("123456")

    assert _wait_for(lambda: runner.GARMIN["status"] == "error")
    assert "no login in progress" in runner.GARMIN["error"]
