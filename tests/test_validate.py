"""Tests for the coach-grade validation gate."""

from __future__ import annotations

from datetime import date, timedelta

from paceforge.engine.planner import generate_plan
from paceforge.engine.validate import validate_plan
from paceforge.models.plan import (
    TrainingPlan,
    Workout,
    WorkoutStep,
    WorkoutStepType,
    WorkoutType,
)
from paceforge.models.profile import (
    ExperienceLevel,
    GoalType,
    TrainingGoal,
    UserFitnessProfile,
)


def _scaffold(
    goal_type: GoalType = GoalType.HALF_MARATHON, weekly_mileage_km: float | None = 45.0
) -> TrainingPlan:
    profile = UserFitnessProfile(vo2_max=52.0, weekly_mileage_km=weekly_mileage_km)
    goal = TrainingGoal(
        goal_type=goal_type,
        target_date=date.today() + timedelta(weeks=12),
        experience_level=ExperienceLevel.INTERMEDIATE,
    )
    return generate_plan(profile, goal)


def test_clean_scaffold_passes_all_gates():
    assert validate_plan(_scaffold()) == []


def test_hyrox_scaffold_passes_all_gates():
    assert validate_plan(_scaffold(GoalType.HYROX, weekly_mileage_km=None)) == []


def test_overlong_interval_rep_is_flagged():
    plan = _scaffold()
    long_rep = Workout(
        workout_type=WorkoutType.INTERVALS,
        name="Monster intervals",
        scheduled_date=date.today() + timedelta(days=3),
        steps=[
            WorkoutStep(step_type=WorkoutStepType.INTERVAL, duration_seconds=600),  # 10 min > 5
        ],
    )
    plan.weeks[0].workouts = [long_rep]
    assert any("interval rep" in i.lower() for i in validate_plan(plan))


def test_oversized_long_run_is_flagged():
    plan = _scaffold()
    wk = plan.weeks[1]
    wk.total_distance_km = 50.0
    wk.workouts = [
        Workout(
            workout_type=WorkoutType.LONG_RUN,
            name="Ultra long",
            scheduled_date=date.today() + timedelta(days=9),
            estimated_distance_meters=25_000,  # 50% of the week
        )
    ]
    assert any("long run" in i.lower() for i in validate_plan(plan))


def test_missing_taper_is_flagged():
    plan = _scaffold()
    # Force the final week to equal the peak week's volume (no taper).
    peak = max(w.total_distance_km or 0 for w in plan.weeks)
    plan.weeks[-1].total_distance_km = peak
    assert any("taper" in i.lower() for i in validate_plan(plan))
