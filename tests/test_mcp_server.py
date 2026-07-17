"""MCP tool wrappers stay thin — each delegates to the right actions/store function."""

from __future__ import annotations

import pytest

from paceforge import actions, mcp_server, store


@pytest.fixture()
def calls(monkeypatch) -> dict:
    """Capture (args, kwargs) of every actions/store call the wrappers make."""
    seen: dict[str, tuple] = {}

    def record(name, result=None):  # noqa: ANN001
        def _fn(*args, **kwargs):
            seen[name] = (args, kwargs)
            return result
        return _fn

    monkeypatch.setattr(actions, "sync", record("sync", {"ok": True}))
    monkeypatch.setattr(actions, "scaffold", record("scaffold", {}))
    monkeypatch.setattr(actions, "analyze", record("analyze", {}))
    monkeypatch.setattr(actions, "validate", record("validate", []))
    monkeypatch.setattr(actions, "push", record("push", {}))
    monkeypatch.setattr(actions, "log_rpe", record("log_rpe", {}))
    monkeypatch.setattr(actions, "link_activity", record("link_activity", {}))
    monkeypatch.setattr(actions, "unlink_activity", record("unlink_activity", {}))
    monkeypatch.setattr(actions, "fitness", record("fitness", {}))
    monkeypatch.setattr(store, "load_profile", record("load_profile"))
    monkeypatch.setattr(store, "load_plan", record("load_plan"))
    return seen


def test_garmin_sync_delegates_lookback_days(calls):
    mcp_server.garmin_sync(lookback_days=30)
    assert calls["sync"] == ((), {"lookback_days": 30})


def test_scaffold_plan_delegates_goal(calls):
    goal = {"goal_type": "MARATHON", "target_date": "2026-10-04"}
    mcp_server.scaffold_plan(goal)
    assert calls["scaffold"] == ((goal,), {})


def test_analyze_delegates(calls):
    mcp_server.analyze()
    assert calls["analyze"] == ((), {})


def test_validate_plan_delegates(calls):
    mcp_server.validate_plan()
    assert calls["validate"] == ((), {})


def test_garmin_push_workout_delegates_week_and_dry_run(calls):
    mcp_server.garmin_push_workout(week=3, dry_run=True)
    assert calls["push"] == ((), {"week": 3, "dry_run": True})


def test_log_rpe_delegates_with_mcp_source(calls):
    mcp_server.log_rpe(7, activity_id=42, duration_min=50.0, notes="hard")
    assert calls["log_rpe"] == ((42, None), {"rpe": 7, "duration_min": 50.0,
                                             "notes": "hard", "source": "mcp"})


def test_link_activity_delegates_date_as_when(calls):
    mcp_server.link_activity(42, date="2026-06-01")
    assert calls["link_activity"] == ((42,), {"session_id": None, "when": "2026-06-01"})


def test_unlink_activity_delegates(calls):
    mcp_server.unlink_activity(42)
    assert calls["unlink_activity"] == ((42,), {})


def test_get_fitness_delegates(calls):
    mcp_server.get_fitness()
    assert calls["fitness"] == ((), {})


def test_get_profile_returns_none_when_no_profile(calls):
    assert mcp_server.get_profile() is None


def test_get_plan_returns_none_when_no_plan(calls):
    assert mcp_server.get_plan() is None
