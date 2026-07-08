"""Tests for the coaching-briefing system."""

from __future__ import annotations

from datetime import date, timedelta

from paceforge.engine.briefings import build_briefing, week_intro
from paceforge.engine.planner import generate_plan
from paceforge.engine.vdot import paces_from_vdot
from paceforge.engine.workouts import WorkoutFactory
from paceforge.models.profile import (
    ExperienceLevel,
    GoalType,
    TrainingGoal,
    UserFitnessProfile,
)


def _plan():
    profile = UserFitnessProfile(vo2_max=54.0, weekly_mileage_km=40.0)
    goal = TrainingGoal(
        goal_type=GoalType.HALF_MARATHON,
        target_date=date.today() + timedelta(weeks=12),
        experience_level=ExperienceLevel.INTERMEDIATE,
    )
    return generate_plan(profile, goal)


def test_every_workout_gets_a_briefing():
    plan = _plan()
    for wk in plan.weeks:
        for w in wk.workouts:
            assert w.briefing, f"wk{wk.week_number} {w.name} has no briefing"
            assert w.briefing.get("purpose")
            assert w.briefing.get("structure")


def test_structure_includes_pace_windows():
    factory = WorkoutFactory(paces_from_vdot(52))
    b = build_briefing(factory.tempo(6))
    assert "/km" in b["structure"]
    assert "→" in b["structure"]


def test_no_unresolved_template_slots():
    plan = _plan()
    for wk in plan.weeks:
        assert "{" not in wk.intro
        for w in wk.workouts:
            for v in (w.briefing or {}).values():
                assert "{" not in v, f"unresolved slot in {w.name}: {v}"


def test_long_runs_carry_fueling_note():
    factory = WorkoutFactory(paces_from_vdot(52))
    b = build_briefing(factory.long_run_with_race_pace(16, race_pace_km=6))
    assert "fuel" in b


def test_hyrox_quality_gets_interference_advice():
    factory = WorkoutFactory(paces_from_vdot(52))
    b = build_briefing(factory.tempo(6), hyrox=True)
    assert "station" in b["if_wrong"].lower()


def test_time_trial_briefing_overrides():
    factory = WorkoutFactory(paces_from_vdot(52))
    b = build_briefing(factory.time_trial(5))
    assert "Benchmark" in b["purpose"]
    assert "venue" in b


def test_week_intro_marks_deload_and_race_week():
    assert "Cutback" in week_intro("Build", 3, 4, deload=True, weeks_to_race=6)
    assert "Race week" in week_intro("Taper", 0, 1, deload=False, weeks_to_race=0)


def test_plan_md_renders(tmp_path, monkeypatch):
    import paceforge.actions as actions
    from paceforge import store

    plan = _plan()
    monkeypatch.setattr(store, "load_plan", lambda: plan)
    out = tmp_path / "plan.md"
    md = actions.plan_md(str(out))
    assert out.exists()
    assert "## Session detail" in md
    assert "**Why:**" in md
    assert "{" not in md.split("## Session detail")[1][:2000]
