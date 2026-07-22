"""commit_push() must commit its own paths and nothing else.

Jobs fire on timers, so one can land while a human (or an agent) is mid-`git add`
in the same checkout. Without a pathspec that unrelated staged work is committed
under a "data:" message and pushed — which is exactly how a workflow deletion
once rode out inside a "data: update upcoming events" commit.
"""

# ruff: noqa: S603, S607  (git in a tmp_path repo, fixed argv)

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo with one commit, no remotes, wired into the runner."""
    git(tmp_path, "init", "-q", "-b", "master")
    git(tmp_path, "config", "user.email", "t@t.t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "plan.json").write_text("{}")
    (tmp_path / "src.py").write_text("original\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return runner.Run("test")


def test_staged_unrelated_work_is_not_swept_into_a_data_commit(repo, run):
    (repo / "data" / "plan.json").write_text('{"weeks": 1}')
    (repo / "src.py").write_text("work in progress\n")
    git(repo, "add", "src.py")

    runner.commit_push(run, ["data/"], "data: daily Garmin sync")

    assert git(repo, "show", "--name-only", "--format=", "HEAD") == "data/plan.json"


def test_the_unrelated_work_is_left_staged(repo, run):
    (repo / "data" / "plan.json").write_text('{"weeks": 1}')
    (repo / "src.py").write_text("work in progress\n")
    git(repo, "add", "src.py")

    runner.commit_push(run, ["data/"], "data: daily Garmin sync")

    assert git(repo, "diff", "--cached", "--name-only") == "src.py"


def test_nothing_to_commit_when_only_unrelated_work_is_staged(repo, run):
    (repo / "src.py").write_text("work in progress\n")
    git(repo, "add", "src.py")
    before = git(repo, "rev-parse", "HEAD")

    runner.commit_push(run, ["data/"], "data: daily Garmin sync")

    assert git(repo, "rev-parse", "HEAD") == before


def test_data_changes_are_committed(repo, run):
    (repo / "data" / "plan.json").write_text('{"weeks": 2}')

    runner.commit_push(run, ["data/"], "data: daily Garmin sync")

    assert git(repo, "log", "-1", "--format=%s") == "data: daily Garmin sync"
