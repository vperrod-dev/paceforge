"""dispatch() must fail cleanly: release JOB_LOCK on exception and alert once.

A raising job has to leave the run marked failed, the global lock released for the
next job, and — for everything except `sync` (which alerts itself with a specific
message) — send exactly one Telegram. A regression here (double-alerting sync, or
a lock the next job blocks on forever) would otherwise pass the suite silently.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def alerts(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(runner, "telegram", lambda text, *a, **k: sent.append(text))
    return sent


def _boom(run, inputs):
    raise RuntimeError("kaboom")


def _run_to_completion(job: str) -> dict:
    run_id = runner.dispatch(job, {})
    rec = next(r for r in runner.RUNS if r["id"] == run_id)
    for _ in range(200):
        if rec["status"] == "completed":
            return rec
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_raising_job_finishes_as_failure(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "boom", _boom)

    rec = _run_to_completion("boom")

    assert rec["conclusion"] == "failure"


def test_raising_job_alerts_once(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "boom", _boom)

    _run_to_completion("boom")

    assert [a for a in alerts if a.startswith("PaceForge job 'boom' failed")] == alerts != []


def test_sync_does_not_double_alert(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "sync", _boom)

    _run_to_completion("sync")

    assert alerts == []


def test_job_lock_is_released_after_failure(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "boom", _boom)

    _run_to_completion("boom")

    assert runner.JOB_LOCK.acquire(blocking=False)
    runner.JOB_LOCK.release()
