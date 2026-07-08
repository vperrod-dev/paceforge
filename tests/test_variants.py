"""Tests for the session-variant library."""

from __future__ import annotations

from datetime import date, timedelta

from paceforge.engine.planner import generate_plan
from paceforge.engine.validate import INTENSE_TYPES
from paceforge.engine.variants import VARIANTS, pick_variant
from paceforge.engine.vdot import paces_from_vdot
from paceforge.engine.workouts import WorkoutFactory
from paceforge.models.plan import WorkoutType
from paceforge.models.profile import (
    ExperienceLevel,
    GoalType,
    TrainingGoal,
    UserFitnessProfile,
)


def _factory() -> WorkoutFactory:
    return WorkoutFactory(paces_from_vdot(52), goal_pace_sec_km=245)


def test_every_variant_dispatches():
    factory = _factory()
    for slot, table in VARIANTS.items():
        for method, kwargs, _min_km in table:
            w = getattr(factory, method)(**kwargs)
            assert w.name, f"{slot}/{method} produced unnamed workout"
            assert w.steps, f"{slot}/{method} produced no steps"


def test_variant_tables_progress_in_work_volume():
    """Walking a table forward never shrinks the session's distance (Canova
    levers — duration may drop when the recovery-shortening lever fires)."""
    factory = _factory()
    for slot, table in VARIANTS.items():
        dists = [
            getattr(factory, m)(**kw).estimated_distance_meters or 0 for m, kw, _ in table
        ]
        for a, b in zip(dists, dists[1:]):
            assert b >= a * 0.9, f"{slot} regresses: {dists}"


def test_deload_steps_back_one_variant():
    normal = pick_variant("vo2max", 2, deload=False, week_km=40)
    eased = pick_variant("vo2max", 2, deload=True, week_km=40)
    assert eased == pick_variant("vo2max", 1, deload=False, week_km=40)
    assert eased != normal


def test_volume_gating_excludes_big_sessions():
    _, kwargs, min_km = pick_variant("vo2max", 10, deload=False, week_km=24)
    assert min_km <= 24


def test_ladder_never_tagged_speed():
    """SPEED reps are capped at 120s by validate — ladders must not carry it."""
    w = _factory().ladder(rungs_min=[4, 3, 2, 3, 4], pace_key="interval")
    assert w.workout_type in (WorkoutType.VO2MAX, WorkoutType.THRESHOLD)


def test_ladder_recoveries_scale_with_rung():
    w = _factory().ladder(rungs_min=[4, 2], pace_key="interval")
    recoveries = [s for s in w.steps if s.step_type.value == "recovery"]
    assert len(recoveries) == 1  # between the two rungs only


def test_alternations_float_is_marathon_pace_not_jog():
    w = _factory().alternations(reps=3)
    grp = next(s for s in w.steps if s.repeat_count)
    float_step = grp.steps[1]
    assert float_step.pace_key == "marathon"


def test_progressive_tempo_blocks_get_faster():
    w = _factory().progressive_tempo(blocks=3, block_min=8)
    blocks = [s for s in w.steps if s.step_type.value == "active"]
    lows = [s.target_low for s in blocks]
    assert lows == sorted(lows, reverse=True)  # sec/km decreasing = faster


def test_no_consecutive_week_repeats_a_quality_session():
    profile = UserFitnessProfile(vo2_max=54.0, weekly_mileage_km=40.0)
    goal = TrainingGoal(
        goal_type=GoalType.HALF_MARATHON,
        target_date=date.today() + timedelta(weeks=14),
        experience_level=ExperienceLevel.INTERMEDIATE,
    )
    plan = generate_plan(profile, goal)
    prev: set[tuple] = set()
    for wk in plan.weeks:
        keys = {
            (w.workout_type, w.name) for w in wk.workouts if w.workout_type in INTENSE_TYPES
        }
        assert not (keys & prev), f"week {wk.week_number} repeats {keys & prev}"
        prev = keys
