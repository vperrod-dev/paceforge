"""Deterministic plan validation.

The AI/validation split: Claude *proposes* a plan (guided by the coach skill),
this module *checks* it. Pure rules, no LLM. ``validate_plan`` returns a list of
human-readable issues — empty means the plan is sound.
"""

from __future__ import annotations

from paceforge.engine.vdot import RACE_DISTANCES, predict_time
from paceforge.models.plan import TrainingPlan, WorkoutStepType, WorkoutType

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

# Interval-rep length ceilings (Daniels): VO2max reps ≤5 min, speed/rep reps ≤2 min.
MAX_INTERVAL_SEC = 5 * 60
MAX_REP_SEC = 2 * 60
_INTERVAL_TYPES: frozenset[WorkoutType] = frozenset({WorkoutType.VO2MAX, WorkoutType.INTERVALS})
_REP_TYPES: frozenset[WorkoutType] = frozenset({WorkoutType.SPEED})

# Long run share of the week scales with run frequency: at 3 days/week the long
# run legitimately carries up to half the volume (the endurance requirement
# doesn't shrink because frequency did); at 5+ the classic ~30% guidance holds
# and we flag only egregious outliers.
def _long_run_cap(run_days: int) -> float:
    if run_days <= 3:
        return 0.50
    if run_days == 4:
        return 0.42
    return 0.37


# A goal more than this much faster than the VDOT prediction is not supported
# by current fitness — every "race pace" session would be mislabeled harder work.
GOAL_FEASIBILITY_MARGIN = 0.02


def validate_plan(plan: TrainingPlan) -> list[str]:
    """Return a list of issues with the plan. Empty list == valid."""
    issues: list[str] = []
    issues += _check_pace_ordering(plan)
    issues += _check_no_back_to_back_hard(plan)
    issues += _check_volume_progression(plan)
    issues += _check_step_paces(plan)
    issues += _check_interval_lengths(plan)
    issues += _check_long_run_cap(plan)
    issues += _check_taper(plan)
    issues += _check_goal_feasibility(plan)
    issues += _check_session_variety(plan)
    issues += _check_weekly_quality(plan)
    return issues


def _iter_interval_steps(workout):  # noqa: ANN001
    """Yield the work-interval steps only, flattening one level of repeat groups.

    Warmup/cooldown/recovery/rest steps are excluded — a 10-min warmup is not an
    over-long rep.
    """
    for step in workout.steps:
        candidates = step.steps if step.steps else [step]
        for s in candidates:
            if s.step_type == WorkoutStepType.INTERVAL:
                yield s


def _check_interval_lengths(plan: TrainingPlan) -> list[str]:
    """VO2max/interval reps ≤5 min; speed/rep reps ≤2 min (only when timed)."""
    issues = []
    for week in plan.weeks:
        for wo in week.workouts:
            if wo.workout_type in _INTERVAL_TYPES:
                cap, label = MAX_INTERVAL_SEC, "interval rep"
            elif wo.workout_type in _REP_TYPES:
                cap, label = MAX_REP_SEC, "rep interval"
            else:
                continue
            for step in _iter_interval_steps(wo):
                dur = step.duration_seconds
                if dur is not None and dur > cap:
                    issues.append(
                        f"Week {week.week_number} '{wo.name}': {label} "
                        f"{dur:.0f}s exceeds {cap}s cap"
                    )
                    break
    return issues


def _check_long_run_cap(plan: TrainingPlan) -> list[str]:
    """No single run may exceed MAX_LONG_RUN_FRAC of its week's volume.

    The final (race) week is exempt — it legitimately contains the race itself.
    """
    issues = []
    for week in plan.weeks[:-1]:
        total = week.total_distance_km
        if not total:
            continue
        run_days = sum(1 for w in week.workouts if w.workout_type != WorkoutType.REST)
        cap = _long_run_cap(run_days)
        for wo in week.workouts:
            km = (wo.estimated_distance_meters or 0) / 1000
            if km > total * cap:
                issues.append(
                    f"Week {week.week_number} '{wo.name}': long run {km:.0f}km is "
                    f"{km / total * 100:.0f}% of the week (>{cap * 100:.0f}% "
                    f"at {run_days} run days)"
                )
                break
    return issues


def _check_taper(plan: TrainingPlan) -> list[str]:
    """The final week must be a taper — below the plan's peak weekly volume."""
    volumes = [(w.week_number, w.total_distance_km) for w in plan.weeks if w.total_distance_km]
    if len(volumes) < 2:
        return []
    peak = max(v for _, v in volumes)
    final_num, final_km = volumes[-1]
    if final_km >= peak:
        return [
            f"Week {final_num}: final week {final_km:.0f}km is not a taper "
            f"(≥ peak {peak:.0f}km)"
        ]
    return []


def _check_session_variety(plan: TrainingPlan) -> list[str]:
    """No identical quality session (type + params) in consecutive weeks.

    Names are param-derived ("6 x 3.5min VO2max Intervals"), so same type+name
    == same session. Repeats ≥2 weeks apart are allowed — benchmark repeats are
    a coaching feature, week-in-week-out monotony is the bug.
    """
    issues = []
    prev_keys: set[tuple] = set()
    for week in plan.weeks:
        keys = {
            (wo.workout_type, wo.name)
            for wo in week.workouts
            if wo.workout_type in INTENSE_TYPES
        }
        for _, name in keys & prev_keys:
            issues.append(
                f"Week {week.week_number}: '{name}' repeats the previous week's session"
            )
        prev_keys = keys
    return issues


def _check_weekly_quality(plan: TrainingPlan) -> list[str]:
    """Every normal training week carries at least one real quality session.

    The 2026-08-10 complaint in rule form: weeks of nothing but easy running
    are exactly what made plans boring, so they now fail validation. Exempt:
    the final (race) week, the Taper phase, and deload/cutback weeks — a
    deload passes with strides (quality steps back, it doesn't vanish) and a
    time trial counts as quality (RACE_PACE). Weeks under 12 km are exempt to
    match the planner's floor guard.
    """
    issues = []
    prev_km: float | None = None
    for week in plan.weeks:
        deload = prev_km is not None and (week.total_distance_km or 0) < prev_km
        prev_km = week.total_distance_km or 0
        if (week.week_number == plan.total_weeks or week.phase == "Taper"
                or (week.total_distance_km or 0) < 12):
            continue
        has_quality = any(w.workout_type in INTENSE_TYPES for w in week.workouts)
        has_strides = any(
            w.workout_type == WorkoutType.EASY_WITH_STRIDES for w in week.workouts
        )
        if has_quality or (deload and has_strides):
            continue
        issues.append(
            f"Week {week.week_number}: no quality session — only easy running "
            "outside taper/recovery"
        )
    return issues


def _check_goal_feasibility(plan: TrainingPlan) -> list[str]:
    """The goal time must be within reach of current fitness (VDOT prediction).

    A goal materially faster than the prediction turns every race-pace session
    into mislabeled supra-threshold work.
    """
    dist = RACE_DISTANCES.get(plan.goal_type)
    if not (plan.target_time_seconds and plan.vdot and dist):
        return []
    predicted = predict_time(dist, plan.vdot)
    if plan.target_time_seconds < predicted * (1 - GOAL_FEASIBILITY_MARGIN):
        goal_m, goal_s = divmod(int(plan.target_time_seconds), 60)
        pred_m, pred_s = divmod(int(predicted), 60)
        return [
            f"Goal {goal_m}:{goal_s:02d} is >{GOAL_FEASIBILITY_MARGIN * 100:.0f}% faster than "
            f"the VDOT {plan.vdot:.1f} prediction ({pred_m}:{pred_s:02d}) — not supported by "
            "current fitness; adjust the target time or earn a VDOT bump first"
        ]
    return []


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
