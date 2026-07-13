"""link_activity()/unlink_activity() — manual pin/exclude of Garmin activities."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout
from paceforge.models.profile import RecentActivity


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _seed(wo_kwargs=None, act_dist=2000):
    d = date(2026, 6, 1)
    wo = Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                 estimated_distance_meters=10000, **(wo_kwargs or {}))
    plan = TrainingPlan(name="t", goal_type="HYROX", target_date=date(2026, 11, 13),
                        total_weeks=1, weeks=[TrainingWeek(week_number=1, workouts=[wo])])
    store.save_plan(plan)
    store.save_activities([RecentActivity(
        activity_id=1, name="run", activity_type="running",
        start_time=datetime(2026, 6, 1, 7, 0),
        distance_meters=act_dist, duration_seconds=act_dist / 3)])
    return wo.session_id


def test_link_pins_activity_that_auto_match_rejects():
    sid = _seed()  # 2 km vs planned 10 km — below the 90% auto-match bar
    result = actions.link_activity(1, session_id=sid)
    wo = store.load_plan().weeks[0].workouts[0]
    assert result["linked"] == 1
    assert wo.matched_activity_ids == [1] and wo.completed


def test_link_by_date_resolves_the_workout():
    _seed()
    actions.link_activity(1, when="2026-06-01")
    assert store.load_plan().weeks[0].workouts[0].matched_activity_ids == [1]


def test_unlink_removes_match_and_blocks_rematch_on_sync():
    _seed(act_dist=10000)  # perfect auto match
    actions._match_plan()
    assert store.load_plan().weeks[0].workouts[0].matched_activity_ids == [1]
    actions.unlink_activity(1)
    actions._match_plan()  # simulate the next sync
    wo = store.load_plan().weeks[0].workouts[0]
    assert wo.matched_activity_ids == [] and not wo.completed
    assert wo.excluded_activity_ids == [1]


def test_unlink_unknown_activity_errors():
    _seed()
    with pytest.raises(RuntimeError, match="not linked"):
        actions.unlink_activity(42)
