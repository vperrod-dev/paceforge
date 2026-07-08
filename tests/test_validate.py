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
            estimated_distance_meters=30_000,  # 60% of the week — over even the 3-day cap
        )
    ]
    assert any("long run" in i.lower() for i in validate_plan(plan))


def test_long_run_cap_scales_with_run_frequency():
    """45% of the week is fine at 3 run days but flagged at 5."""
    plan = _scaffold()
    wk = plan.weeks[1]
    wk.total_distance_km = 40.0
    long = Workout(
        workout_type=WorkoutType.LONG_RUN,
        name="Big long run",
        scheduled_date=date.today() + timedelta(days=9),
        estimated_distance_meters=18_000,  # 45%
    )
    easy = [
        Workout(
            workout_type=WorkoutType.EASY_RUN,
            name=f"easy-{i}",
            scheduled_date=date.today() + timedelta(days=10 + i),
            estimated_distance_meters=5_500,
        )
        for i in range(4)
    ]
    wk.workouts = [long, *easy[:2]]  # 3 run days
    assert not any("long run" in i.lower() for i in validate_plan(plan))
    wk.workouts = [long, *easy]  # 5 run days
    assert any("long run" in i.lower() for i in validate_plan(plan))


def test_missing_taper_is_flagged():
    plan = _scaffold()
    # Force the final week to equal the peak week's volume (no taper).
    peak = max(w.total_distance_km or 0 for w in plan.weeks)
    plan.weeks[-1].total_distance_km = peak
    assert any("taper" in i.lower() for i in validate_plan(plan))


def test_infeasible_goal_time_is_flagged():
    """A target >2% faster than the VDOT prediction fails validation."""
    plan = _scaffold()
    plan.target_time_seconds = 70 * 60  # 70:00 half at VDOT ~52 is fantasy
    assert any("faster than" in i for i in validate_plan(plan))


def test_feasible_goal_time_passes():
    plan = _scaffold()
    plan.target_time_seconds = 95 * 60  # comfortably within VDOT ~52
    assert not any("faster than" in i for i in validate_plan(plan))


def test_week_one_anchored_to_actual_mileage():
    """Low-mileage athlete must not open at template volume (ACWR guard)."""
    lo = _scaffold(weekly_mileage_km=15.0)
    assert lo.weeks[0].total_distance_km <= 15.0 * 1.3  # ACWR ceiling
    hi = _scaffold(weekly_mileage_km=45.0)
    assert hi.weeks[0].total_distance_km > lo.weeks[0].total_distance_km


def test_three_day_week_keeps_an_easy_run():
    """At 3 run days a hard long-run subtype must consume a quality slot."""
    profile = UserFitnessProfile(vo2_max=52.0, weekly_mileage_km=30.0)
    goal = TrainingGoal(
        goal_type=GoalType.HALF_MARATHON,
        target_date=date.today() + timedelta(weeks=12),
        experience_level=ExperienceLevel.INTERMEDIATE,
        max_days_per_week=3,
    )
    plan = generate_plan(profile, goal)
    hard_lr = {WorkoutType.LONG_RUN_PROGRESSIVE, WorkoutType.LONG_RUN_WITH_RACE_PACE}
    easy_types = {WorkoutType.EASY_RUN, WorkoutType.EASY_WITH_STRIDES, WorkoutType.RECOVERY}
    for wk in plan.weeks[:-1]:
        if any(w.workout_type in hard_lr for w in wk.workouts):
            assert any(w.workout_type in easy_types for w in wk.workouts), (
                f"week {wk.week_number}: hard long run with no easy running"
            )
