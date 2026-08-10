"""WS2 (2026-08-10): intake-driven planning + variety engine regression tests.

The complaint in test form: a low-volume athlete's plan must still contain
real, varied quality work, sized and paced from what the athlete STATED —
never capped by scraped Garmin history.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceforge.engine.adaptation import hold_back_progression
from paceforge.engine.planner import generate_plan
from paceforge.engine.validate import INTENSE_TYPES, _check_weekly_quality, validate_plan
from paceforge.engine.variants import VARIANTS
from paceforge.engine.workouts import WorkoutFactory
from paceforge.models.plan import WorkoutType
from paceforge.models.profile import (
    ExperienceLevel,
    GoalType,
    TrainingGoal,
    UserFitnessProfile,
)


def _low_volume_profile() -> UserFitnessProfile:
    return UserFitnessProfile(vo2_max=53.4, weekly_mileage_km=15.3)


def _intake_goal(**over) -> TrainingGoal:
    kw = dict(
        goal_type=GoalType.HALF_MARATHON,
        target_date=date.today() + timedelta(weeks=12),
        experience_level=ExperienceLevel.INTERMEDIATE,
        training_days=["tuesday", "thursday", "sunday"],
        long_run_day="sunday",
        recent_race_distance="10K",
        recent_race_seconds=3150.0,
        current_weekly_km=18.0,
        target_time_seconds=115 * 60.0,
    )
    kw.update(over)
    return TrainingGoal(**kw)


def test_paces_come_from_stated_race_not_device():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    assert plan.pace_source.startswith("Stated recent 10K")
    assert plan.vdot == pytest.approx(37.8, abs=0.5)  # 52:30 10K, not VO2max 53.4


def test_low_volume_athlete_keeps_quality_every_week():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    for week in plan.weeks:
        if week.phase == "Taper" or week.week_number == plan.total_weeks:
            continue
        assert any(w.workout_type in INTENSE_TYPES for w in week.workouts), (
            f"week {week.week_number} has no quality session"
        )


def test_plan_has_varied_quality_names():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    names = {
        w.name for week in plan.weeks for w in week.workouts
        if w.workout_type in INTENSE_TYPES
    }
    assert len(names) >= 6


def test_no_consecutive_week_repeats_at_low_volume():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    prev: set[str] = set()
    for week in plan.weeks:
        cur = {w.name for w in week.workouts if w.workout_type in INTENSE_TYPES}
        assert not (cur & prev), f"week {week.week_number} repeats {cur & prev}"
        prev = cur


def test_same_intake_regenerates_identically():
    a = generate_plan(_low_volume_profile(), _intake_goal())
    b = generate_plan(_low_volume_profile(), _intake_goal())
    assert [w.name for wk in a.weeks for w in wk.workouts] == \
           [w.name for wk in b.weeks for w in wk.workouts]


def test_different_race_date_rotates_differently():
    a = generate_plan(_low_volume_profile(), _intake_goal())
    b = generate_plan(_low_volume_profile(),
                      _intake_goal(target_date=date.today() + timedelta(weeks=13)))
    assert [w.name for wk in a.weeks for w in wk.workouts] != \
           [w.name for wk in b.weeks for w in wk.workouts]


def test_declared_volume_governs_ramp_not_history():
    prof = _low_volume_profile()   # history says 15.3
    plan = generate_plan(prof, _intake_goal(current_weekly_km=30.0))
    assert plan.weeks[0].total_distance_km >= 25  # ~declared*1.15, not history-capped


def test_intake_stored_on_plan():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    assert plan.intake["recent_race_distance"] == "10K"
    assert plan.intake["current_weekly_km"] == 18.0


def test_every_slot_has_low_volume_variant():
    for slot, table in VARIANTS.items():
        assert min(v[2] for v in table) <= 16, f"{slot} has no low-volume row"


def test_fartlek_dose_scales_with_duration():
    f = WorkoutFactory(None)
    short, long_ = f.fartlek(25), f.fartlek(45)
    reps = lambda w: next(s.repeat_count for s in w.steps if s.repeat_count)  # noqa: E731
    assert reps(short) < reps(long_)
    assert short.name != long_.name


def test_validator_flags_quality_free_week():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    wk = next(w for w in plan.weeks if w.phase == "Build")
    for w in wk.workouts:
        if w.workout_type in INTENSE_TYPES:
            w.workout_type = WorkoutType.EASY_RUN
    issues = _check_weekly_quality(plan)
    assert any(f"Week {wk.week_number}" in i and "no quality session" in i for i in issues)


def test_hold_back_progression_repeats_failed_flavor():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    today = date.today()
    keyed = [w for wk in plan.weeks for w in wk.workouts if w.variant_key]
    # Two occurrences of one flavor, in order
    taper_weeks = {wk.week_number for wk in plan.weeks if wk.phase == "Taper"}
    week_of = {w.session_id: wk.week_number for wk in plan.weeks for w in wk.workouts}
    by_flavor: dict[str, list] = {}
    for w in keyed:
        by_flavor.setdefault(":".join(w.variant_key.split(":")[:2]), []).append(w)
    # Hold-back never touches the taper, so pick a flavor recurring before it.
    flavor, pair = next(
        (f, ws) for f, ws in by_flavor.items()
        if len(ws) >= 2 and week_of[ws[1].session_id] not in taper_weeks
    )
    first, second = pair[0], pair[1]
    first.scheduled_date = today - timedelta(days=3)
    first.completed = True
    first.completion_metrics = {"status": "red"}
    second.scheduled_date = today + timedelta(days=4)
    changes = hold_back_progression(plan, today)
    assert changes, "expected a hold-back"
    replaced = next(w for wk in plan.weeks for w in wk.workouts
                    if w.scheduled_date == today + timedelta(days=4)
                    and w.variant_key == first.variant_key)
    assert replaced.name == first.name
    assert not replaced.completed


def test_full_plan_validates_clean():
    plan = generate_plan(_low_volume_profile(), _intake_goal())
    assert validate_plan(plan) == []
