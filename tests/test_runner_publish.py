"""publish() must never fail the enclosing job.

A broken build_site_data.py only means the derived JSON is stale; before this
guard the RuntimeError it raised failed whatever unrelated job (save-rpe,
calendar-edit, …) happened to trigger the publish step.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return runner.Run("test")


def _stub_build(monkeypatch, returncode):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout="build output\n", stderr="")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)


def test_publish_failure_does_not_raise_inside_a_job(run, monkeypatch):
    _stub_build(monkeypatch, 1)

    runner.publish(run)  # must not raise


def test_publish_failure_marks_the_run(run, monkeypatch):
    _stub_build(monkeypatch, 1)

    runner.publish(run)

    assert run.rec["publish_failed"] is True


def test_publish_failure_is_logged(run, monkeypatch):
    _stub_build(monkeypatch, 1)

    runner.publish(run)

    assert "derived data is stale" in run.log_path.read_text()


def test_publish_success_leaves_run_unmarked(run, monkeypatch):
    _stub_build(monkeypatch, 0)

    runner.publish(run)

    assert "publish_failed" not in run.rec


def test_standalone_publish_still_fails_loudly(monkeypatch):
    _stub_build(monkeypatch, 1)

    with pytest.raises(RuntimeError, match="build_site_data"):
        runner.publish(None)
