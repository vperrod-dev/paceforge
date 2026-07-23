"""The coach agent runs on user/Garmin-supplied text, so its Bash grant must not
include bare python/python3 — that would be arbitrary local code execution."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


def _captured_coach_tools(monkeypatch) -> str:
    grant: dict[str, str] = {}
    monkeypatch.setattr(runner, "sh", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "publish", lambda *a, **k: None)
    monkeypatch.setattr(runner, "telegram", lambda *a, **k: None)
    monkeypatch.setattr(runner, "claude_step",
                        lambda run, prompt, tools, **k: grant.update(tools=tools))
    runner.job_coach(SimpleNamespace(step=lambda *a: None, log=lambda *a: None),
                     {"instruction": "review my week"})
    return grant["tools"]


def test_coach_grant_excludes_bare_python(monkeypatch):
    assert "python" not in _captured_coach_tools(monkeypatch)


def test_coach_grant_keeps_paceforge_and_git(monkeypatch):
    tools = _captured_coach_tools(monkeypatch)
    assert "Bash(paceforge:*)" in tools and "Bash(git:*)" in tools
