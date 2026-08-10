"""WS1: light-sync cooldown, dispatch coalescing, day-pulse slot logic."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


def test_cooldown_write_levels_double_and_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
    for level, mins in ((1, 15), (2, 30), (3, 60), (4, 120), (9, 120)):
        runner._cooldown_write(level)
        cd = runner._cooldown_read()
        until = datetime.strptime(cd["until"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        delta = until - datetime.now(UTC)
        assert timedelta(minutes=mins - 1) < delta < timedelta(minutes=mins + 1)


def test_cooldown_reset_clears_until(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
    runner._cooldown_write(2)
    runner._cooldown_write(0)
    assert runner._cooldown_read() == {"level": 0, "until": ""}


def test_sync_rate_limited_detects_429(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    d = tmp_path / "data"
    d.mkdir()
    (d / "sync-status.json").write_text(json.dumps(
        {"result": "partial", "endpoints": {"hrv": {"ok": False, "error": "HTTP 429"}}}))
    assert runner._sync_rate_limited() is True
    (d / "sync-status.json").write_text(json.dumps(
        {"result": "ok", "endpoints": {"hrv": {"ok": True}}}))
    assert runner._sync_rate_limited() is False


def test_dispatch_coalesces_queued_same_job(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)  # keep runs.jsonl out of live state
    started = []
    monkeypatch.setitem(runner.JOBS, "noop-test", lambda run, inputs: started.append(run.id))
    # Hold the lock so dispatched jobs stay queued.
    with runner.JOB_LOCK:
        first = runner.dispatch("noop-test", {})
        second = runner.dispatch("noop-test", {})
        assert first == second
    # Wait for the worker daemon-thread to finish INSIDE the monkeypatched
    # STATE_DIR — otherwise its runs.jsonl write lands in live state.
    import time
    deadline = time.time() + 5
    while time.time() < deadline:
        rec = next(r for r in runner.RUNS if r["id"] == first)
        if rec["status"] == "completed":
            break
        time.sleep(0.05)
    assert started == [first]


def test_maybe_day_pulse_once_per_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    d = tmp_path / "data"
    d.mkdir()
    dublin = datetime.now(runner.ZoneInfo("Europe/Dublin"))
    today = dublin.strftime("%Y-%m-%d")
    slot = f"{today}T{dublin.hour:02d}"
    (d / "daily-brief.json").write_text(json.dumps(
        {"date": today, "headline": "x", "pulses": [{"slot": slot, "text": "done"}]}))
    calls = []
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: calls.append((job, inputs)))
    monkeypatch.setattr(runner, "_PULSE_HOURS", (dublin.hour,))
    runner._maybe_day_pulse()
    assert calls == []          # slot already pulsed
    (d / "daily-brief.json").write_text(json.dumps({"date": today, "headline": "x"}))
    runner._maybe_day_pulse()
    assert calls == [("day-pulse", {"slot": slot})]
