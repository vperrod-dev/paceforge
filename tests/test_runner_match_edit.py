"""The match-edit job is the portal's manual link/unmatch control.

It must call the right action for the action it was given and commit the plan —
a job that silently linked when the user asked to unmatch would re-attach the
activity the athlete just said didn't happen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return runner.Run("match-edit")


@pytest.fixture
def calls(monkeypatch):
    from paceforge import actions
    seen: dict = {}
    monkeypatch.setattr(actions, "link_activity",
                        lambda aid, session_id=None, when=None: seen.update(link=(aid, session_id)))
    monkeypatch.setattr(actions, "unlink_activity", lambda aid: seen.update(unlink=aid))
    monkeypatch.setattr(runner, "commit_push", lambda run, paths, msg: seen.update(commit=(paths, msg)))
    monkeypatch.setattr(runner, "publish", lambda run: None)
    return seen


def test_link_pins_the_activity_to_the_session(run, calls):
    runner.job_match_edit(run, {"action": "link", "activity_id": "42", "session_id": "abc123"})

    assert calls["link"] == (42, "abc123")


def test_unlink_detaches_the_activity(run, calls):
    runner.job_match_edit(run, {"action": "unlink", "activity_id": "42"})

    assert calls["unlink"] == 42


def test_unlink_never_links(run, calls):
    runner.job_match_edit(run, {"action": "unlink", "activity_id": "42", "session_id": "abc123"})

    assert "link" not in calls


def test_the_plan_change_is_committed(run, calls):
    runner.job_match_edit(run, {"action": "unlink", "activity_id": "42"})

    assert calls["commit"] == (["data/plan.json"], "calendar: unlink activity 42")


def test_the_job_is_registered_for_dispatch():
    assert runner.JOBS["match-edit"] is runner.job_match_edit
