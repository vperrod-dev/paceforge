"""Deterministic plan validation.

The AI/validation split: Claude *proposes* a plan (guided by the coach skill),
this module *checks* it. Pure rules, no LLM. ``validate_plan`` returns a list of
human-readable issues — empty means the plan is sound.
"""

from __future__ import annotations

from paceforge.models.plan import TrainingPlan, WorkoutType

# Intense quality sessions — two of THESE on consecutive days is a red flag.
# Long runs are excluded on purpose: a quality day before the weekend long run is a
# normal, intentional pattern (the template schedules it), not an error.
INTENSE_TYPES: frozenset[WorkoutType] = frozenset({
    WorkoutType.TEMPO,
    WorkoutType.INTERVALS,
    WorkoutType.THRESHOLD,
    WorkoutType.RACE_PACE,
    WorkoutType.VO2MAX,
    WorkoutType.HILLS,
    WorkoutType.SPEED,
    WorkoutType.FARTLEK,
    WorkoutType.PROGRESSIVE,
    WorkoutType.HYROX_MIXED,  # bricks/simulations are quality work, not easy days
})

MAX_WEEKLY_RAMP = 0.15  # >15% week-over-week build is injury territory


def validate_plan(plan: TrainingPlan) -> list[str]:
    """Return a list of issues with the plan. Empty list == valid."""
    issues: list[str] = []
    issues += _check_pace_ordering(plan)
    issues += _check_no_back_to_back_hard(plan)
    issues += _check_volume_progression(plan)
    issues += _check_step_paces(plan)
    return issues


def _check_pace_ordering(plan: TrainingPlan) -> list[str]:
    """Paces in sec/km must get faster (smaller) from easy → repetition."""
    labelled = [
        ("easy", plan.easy_pace),
        ("marathon", plan.marathon_pace),
        ("threshold", plan.threshold_pace),
        ("interval", plan.interval_pace),
        ("repetition", plan.repetition_pace),
    ]
    present = [(name, p) for name, p in labelled if p is not None]
    issues = []
    for (a_name, a), (b_name, b) in zip(present, present[1:]):
        if a <= b:
            issues.append(
                f"Pace ordering: {a_name} ({a:.0f}s/km) should be slower than "
                f"{b_name} ({b:.0f}s/km)"
            )
    return issues


def _check_no_back_to_back_hard(plan: TrainingPlan) -> list[str]:
    issues = []
    for week in plan.weeks:
        dated = sorted(
            (w for w in week.workouts if w.scheduled_date and w.workout_type in INTENSE_TYPES),
            key=lambda w: w.scheduled_date,  # type: ignore[arg-type, return-value]
        )
        for prev, cur in zip(dated, dated[1:]):
            if (cur.scheduled_date - prev.scheduled_date).days == 1:  # type: ignore[operator]
                issues.append(
                    f"Week {week.week_number}: back-to-back hard days "
                    f"{prev.scheduled_date} ({prev.workout_type.value}) → "
                    f"{cur.scheduled_date} ({cur.workout_type.value})"
                )
    return issues


def _check_volume_progression(plan: TrainingPlan) -> list[str]:
    issues = []
    weeks = [w for w in plan.weeks if w.total_distance_km]
    for i in range(1, len(weeks)):
        prev_km = weeks[i - 1].total_distance_km
        cur_km = weeks[i].total_distance_km
        if not (prev_km and cur_km):
            continue
        # A rebound from a cutback week is expected — skip when the previous week
        # was itself a dip below the week before it.
        before = weeks[i - 2].total_distance_km if i >= 2 else None
        if before and prev_km < before:
            continue
        if cur_km > prev_km * (1 + MAX_WEEKLY_RAMP):
            issues.append(
                f"Week {weeks[i].week_number}: volume jumps "
                f"{prev_km:.0f}→{cur_km:.0f}km ({(cur_km / prev_km - 1) * 100:.0f}% > "
                f"{MAX_WEEKLY_RAMP * 100:.0f}%)"
            )
    return issues


def _check_step_paces(plan: TrainingPlan) -> list[str]:
    """Step pace targets must sit within a sane envelope around the plan paces."""
    if not plan.repetition_pace or not plan.easy_pace:
        return []
    floor = plan.repetition_pace * 0.85  # faster than rep pace is implausible
    ceil = plan.easy_pace * 1.15  # slower than easy+15% is a walk
    issues = []
    for week in plan.weeks:
        for wo in week.workouts:
            for step in wo.steps:
                for edge in (step.target_low, step.target_high):
                    if edge is not None and not (floor <= edge <= ceil):
                        issues.append(
                            f"Week {week.week_number} '{wo.name}': pace target "
                            f"{edge:.0f}s/km outside [{floor:.0f},{ceil:.0f}]"
                        )
                        break
    return issues


def demo() -> None:
    """Self-check: a template plan passes; a deliberately broken plan fails."""
    from datetime import date, timedelta

    from paceforge.engine.planner import generate_plan
    from paceforge.models.profile import (
        ExperienceLevel,
        GoalType,
        TrainingGoal,
        UserFitnessProfile,
    )

    profile = UserFitnessProfile(vo2_max=52.0, weekly_mileage_km=45.0)
    goal = TrainingGoal(
        goal_type=GoalType.HALF_MARATHON,
        target_date=date.today() + timedelta(weeks=12),
        experience_level=ExperienceLevel.INTERMEDIATE,
    )
    good = generate_plan(profile, goal)
    good_issues = validate_plan(good)
    assert good_issues == [], f"template plan should validate, got: {good_issues}"

    # Break it: invert two paces and put two hard days back-to-back.
    bad = good.model_copy(deep=True)
    bad.easy_pace, bad.repetition_pace = bad.repetition_pace, bad.easy_pace
    wk = bad.weeks[1]
    d = date.today() + timedelta(days=2)
    for offset, wt in enumerate((WorkoutType.INTERVALS, WorkoutType.TEMPO)):
        wk.workouts.append(
            type(wk.workouts[0])(
                workout_type=wt, name=f"hard-{offset}",
                scheduled_date=d + timedelta(days=offset),
            )
        )
    bad_issues = validate_plan(bad)
    assert any("Pace ordering" in i for i in bad_issues), bad_issues
    assert any("back-to-back" in i for i in bad_issues), bad_issues
    print(f"OK — template plan valid; broken plan flagged {len(bad_issues)} issues")


if __name__ == "__main__":
    demo()
