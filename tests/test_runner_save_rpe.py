"""Logging an RPE has to re-evaluate the session, not just store a number.

The coach analysis is written once and skipped ever after (pending_analyses skips
ids that already have a file), so an analysis written before the rating existed
reads "no RPE logged" forever unless saving one drops it. The plan's user_rpe
likewise only lands via a re-match.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def data(tmp_path, monkeypatch):
    (tmp_path / "data" / "analyses").mkdir(parents=True)
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return tmp_path / "data"


@pytest.fixture
def calls(monkeypatch):
    from paceforge import actions
    seen: dict = {}
    monkeypatch.setattr(actions, "_match_plan", lambda: seen.setdefault("matched", True))
    monkeypatch.setattr(runner, "commit_push", lambda run, paths, msg: seen.update(paths=paths))
    monkeypatch.setattr(runner, "publish", lambda run: None)
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: seen.update(dispatched=job))
    return seen


def _save(data, calls, aid=42):
    run = runner.Run("save-rpe")
    runner.job_save_rpe(run, {"data": {"activity_id": aid, "date": "2026-08-04", "rpe": 7}})
    return run


def test_the_rating_is_stored(data, calls):
    _save(data, calls)

    assert '"rpe": 7' in (data / "rpe.json").read_text()


def test_the_stale_analysis_is_dropped(data, calls):
    (data / "analyses" / "42.md").write_text("no RPE logged for this session")

    _save(data, calls)

    assert not (data / "analyses" / "42.md").exists()


def test_the_coach_is_asked_to_re_analyse(data, calls):
    (data / "analyses" / "42.md").write_text("old")

    _save(data, calls)

    assert calls["dispatched"] == "analyze"


def test_no_re_analysis_when_the_session_was_never_analysed(data, calls):
    _save(data, calls)

    assert "dispatched" not in calls


def test_the_rating_is_copied_onto_the_plan(data, calls):
    _save(data, calls)

    assert calls["matched"] is True


def test_the_dropped_analysis_is_committed(data, calls):
    (data / "analyses" / "42.md").write_text("old")

    _save(data, calls)

    assert calls["paths"] == ["data/rpe.json", "data/plan.json", "data/analyses/42.md"]
