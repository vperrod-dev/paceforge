"""Plan adaptation — adjust upcoming workouts based on completed activity data."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from paceforge.engine.vdot import TrainingPaces, paces_from_race, paces_from_vdot
from paceforge.models.plan import (
    IntensityTarget,
    TrainingPlan,
    Workout,
    WorkoutType,
)
from paceforge.models.profile import UserFitnessProfile

logger = logging.getLogger(__name__)


def adapt_plan(
    plan: TrainingPlan,
    profile: UserFitnessProfile,
    custom_paces: dict[str, float] | None = None,
) -> TrainingPlan:
    """Re-evaluate and adapt a plan based on latest fitness data.

    Adjustments:
    1. Apply manual pace overrides (if provided), otherwise recalculate from VDOT
    2. Detect missed workouts → redistribute or skip
    3. Detect overtraining signals (low HRV, low readiness) → add recovery
    """
    today = date.today()

    # 1. Apply custom paces if provided, otherwise recalculate from fitness data
    if custom_paces:
        plan = _apply_custom_paces(plan, custom_paces)
    else:
        new_paces = _recalculate_paces(profile, plan)
        if new_paces:
            plan = _update_plan_paces(plan, new_paces)

    # 2. Check for overtraining signals
    needs_recovery = _check_recovery_needed(profile)
    if needs_recovery:
        plan = _inject_recovery(plan, today)

    # 3. Detect missed workouts and adjust
    plan = _handle_missed_workouts(plan, profile, today)

    return plan


def _apply_custom_paces(plan: TrainingPlan, custom_paces: dict[str, float]) -> TrainingPlan:
    """Apply manually-entered pace overrides to the plan and update future workout steps."""
    today = date.today()

    # Update plan-level pace fields
    if "easy_pace" in custom_paces:
        plan.easy_pace = custom_paces["easy_pace"]
    if "marathon_pace" in custom_paces:
        plan.marathon_pace = custom_paces["marathon_pace"]
    if "threshold_pace" in custom_paces:
        plan.threshold_pace = custom_paces["threshold_pace"]
    if "interval_pace" in custom_paces:
        plan.interval_pace = custom_paces["interval_pace"]

    # Build a TrainingPaces-compatible object to reuse _update_step_pace
    paces = TrainingPaces(
        vdot=plan.vdot or 0,
        easy_low=plan.easy_pace or 0,
        easy_high=(plan.easy_pace or 0) + 15,  # ~15s range for easy zone
        marathon=plan.marathon_pace or 0,
        threshold=plan.threshold_pace or 0,
        interval=plan.interval_pace or 0,
        repetition=plan.repetition_pace or (plan.interval_pace or 0) - 10,
    )

    for week in plan.weeks:
        for workout in week.workouts:
            if workout.scheduled_date and workout.scheduled_date <= today:
                continue
            for step in workout.steps:
                if step.target_type == IntensityTarget.PACE:
                    _update_step_pace(step, paces)
                if step.steps:
                    for sub in step.steps:
                        if sub.target_type == IntensityTarget.PACE:
                            _update_step_pace(sub, paces)

    plan.pace_source = "Manual override"
    logger.info("Applied custom paces: %s", custom_paces)
    return plan


def _recalculate_paces(
    profile: UserFitnessProfile,
    plan: TrainingPlan,
) -> TrainingPaces | None:
    """Check if fitness has improved and update paces accordingly."""
    if profile.vo2_max and plan.easy_pace:
        new_paces = paces_from_vdot(profile.vo2_max)
        old_easy = plan.easy_pace

        # Only update if meaningful change (> 3 sec/km)
        if abs(new_paces.easy_low - old_easy) > 3:
            logger.info(
                "VDOT pace update: easy %s → %s sec/km",
                round(old_easy, 1),
                round(new_paces.easy_low, 1),
            )
            return new_paces

    # Check if a recent hard effort suggests higher fitness
    fast_runs = [
        a for a in profile.recent_activities
        if a.avg_pace_sec_per_km
        and a.distance_meters > 3000
        and a.training_effect_aerobic
        and a.training_effect_aerobic >= 3.0
    ]
    if fast_runs:
        best = min(fast_runs, key=lambda a: a.avg_pace_sec_per_km or 999)
        if best.avg_pace_sec_per_km and best.distance_meters > 3000:
            new_paces = paces_from_race(best.distance_meters, best.duration_seconds)
            if plan.easy_pace and abs(new_paces.easy_low - plan.easy_pace) > 3:
                return new_paces

    return None


def _update_plan_paces(plan: TrainingPlan, paces: TrainingPaces) -> TrainingPlan:
    """Update all future workout pace targets in the plan."""
    today = date.today()
    plan.easy_pace = paces.easy_low
    plan.marathon_pace = paces.marathon
    plan.threshold_pace = paces.threshold
    plan.interval_pace = paces.interval
    plan.repetition_pace = paces.repetition

    for week in plan.weeks:
        for workout in week.workouts:
            if workout.scheduled_date and workout.scheduled_date <= today:
                continue  # Don't modify past workouts
            for step in workout.steps:
                if step.target_type == IntensityTarget.PACE:
                    _update_step_pace(step, paces)
                if step.steps:
                    for sub in step.steps:
                        if sub.target_type == IntensityTarget.PACE:
                            _update_step_pace(sub, paces)

    return plan


def _update_step_pace(step, paces: TrainingPaces) -> None:  # noqa: ANN001
    """Update a single step's pace targets based on the range."""
    if step.target_low is None:
        return

    # Determine which pace zone this step is targeting by checking proximity
    old_mid = ((step.target_low or 0) + (step.target_high or 0)) / 2

    candidates = [
        (paces.easy_low, paces.easy_high, "easy"),
        (paces.marathon - 3, paces.marathon + 3, "marathon"),
        (paces.threshold - 3, paces.threshold + 3, "threshold"),
        (paces.interval - 3, paces.interval + 3, "interval"),
        (paces.repetition - 3, paces.repetition + 3, "repetition"),
    ]

    best_match = min(candidates, key=lambda c: abs((c[0] + c[1]) / 2 - old_mid))
    step.target_low = best_match[0]
    step.target_high = best_match[1]


def _check_recovery_needed(profile: UserFitnessProfile) -> bool:
    """Check overtraining signals."""
    if profile.hrv_status and profile.hrv_status.lower() in ("low", "poor", "unbalanced"):
        return True
    return bool(profile.training_readiness is not None and profile.training_readiness < 25)


def _inject_recovery(plan: TrainingPlan, today: date) -> TrainingPlan:
    """Convert the next hard workout into an easy/recovery run."""
    for week in plan.weeks:
        for i, workout in enumerate(week.workouts):
            if not workout.scheduled_date or workout.scheduled_date <= today:
                continue
            if workout.workout_type in (
                WorkoutType.INTERVALS,
                WorkoutType.TEMPO,
                WorkoutType.THRESHOLD,
            ):
                logger.info(
                    "Recovery override: converting %s on %s to easy run",
                    workout.name,
                    workout.scheduled_date,
                )
                week.workouts[i] = Workout(
                    workout_type=WorkoutType.EASY_RUN,
                    name=f"Recovery (was: {workout.name})",
                    description="Converted to easy run due to low recovery signals",
                    scheduled_date=workout.scheduled_date,
                    estimated_duration_seconds=workout.estimated_duration_seconds,
                    estimated_distance_meters=(workout.estimated_distance_meters or 0) * 0.7,
                    steps=[],
                )
                return plan  # Only convert one workout
    return plan


def reflow_missed_sessions(plan: TrainingPlan, today: date | None = None) -> list[str]:
    """Move this week's missed quality session into a later easy slot, same week.

    No "punishment" catch-up: one missed quality session moves forward onto an
    easy day if the spacing rules survive; if the week has no safe slot it is
    simply dropped (the note records that). Never stacks two hard days.
    Mutates the plan in place; returns human-readable change descriptions.
    """
    from paceforge.engine.validate import INTENSE_TYPES

    today = today or date.today()
    changes: list[str] = []
    for week in plan.weeks:
        dated = [w for w in week.workouts if w.scheduled_date]
        if not dated or not (min(w.scheduled_date for w in dated) <= today
                             <= max(w.scheduled_date for w in dated)):
            continue
        hard_dates = {w.scheduled_date for w in dated
                      if w.workout_type in INTENSE_TYPES and not _is_missed(w, today)}
        for missed in dated:
            if not (_is_missed(missed, today) and missed.workout_type in INTENSE_TYPES):
                continue
            slot = next(
                (w for w in dated
                 if w.scheduled_date > today
                 and w.workout_type in (WorkoutType.EASY_RUN, WorkoutType.RECOVERY)
                 and not _adjacent_to_hard(w.scheduled_date, hard_dates)),
                None,
            )
            if slot is None:
                missed.notes = (missed.notes + " [Missed — dropped, no safe slot this week; "
                                               "don't cram it]").strip()
                changes.append(f"Dropped missed {missed.name} (no safe slot left this week)")
                continue
            old_date, new_date = missed.scheduled_date, slot.scheduled_date
            missed.scheduled_date = new_date
            missed.completion_metrics = None
            missed.notes = (missed.notes + f" [Moved from {old_date} after being missed]").strip()
            week.workouts.remove(slot)  # the easy run gives way — volume, not fitness, is lost
            hard_dates.add(new_date)
            changes.append(f"Moved missed {missed.name} {old_date} → {new_date} "
                           f"(replaced {slot.name})")
    return changes


def _is_missed(w: Workout, today: date) -> bool:
    status = (w.completion_metrics or {}).get("status")
    return (status == "red") or (w.scheduled_date < today and not w.completed)


def _adjacent_to_hard(d: date, hard_dates: set) -> bool:
    return any(abs((d - h).days) <= 1 for h in hard_dates if h)


def readiness_gate(plan: TrainingPlan, readiness: dict | None,
                   yesterday_rpe: int | None = None,
                   today: date | None = None) -> list[str]:
    """Downgrade imminent quality work when the athlete shouldn't do it.

    Fires when the readiness composite band is low, or yesterday's session was
    rated RPE >= 9 (a max effort needs an easy day after it regardless of what
    the wellness numbers say). Converts the next intense workout within 2 days
    to an easy run at 70% volume. Returns change descriptions.
    """
    from paceforge.engine.validate import INTENSE_TYPES

    today = today or date.today()
    band = (readiness or {}).get("band")
    reason = None
    if band == "low":
        reason = f"readiness {readiness.get('score')} (low)"
    elif yesterday_rpe is not None and yesterday_rpe >= 9:
        reason = f"yesterday rated RPE {yesterday_rpe}/10"
    if not reason:
        return []

    for week in plan.weeks:
        for i, workout in enumerate(week.workouts):
            if (workout.scheduled_date and workout.workout_type in INTENSE_TYPES
                    and today <= workout.scheduled_date <= today + timedelta(days=2)):
                week.workouts[i] = Workout(
                    workout_type=WorkoutType.EASY_RUN,
                    name=f"Recovery (was: {workout.name})",
                    description=f"Downgraded — {reason}. The hard work waits until you can absorb it.",
                    scheduled_date=workout.scheduled_date,
                    estimated_duration_seconds=workout.estimated_duration_seconds,
                    estimated_distance_meters=(workout.estimated_distance_meters or 0) * 0.7,
                    purpose=workout.purpose,
                )
                return [f"Downgraded {workout.name} on {workout.scheduled_date} to easy — {reason}"]
    return []


def _handle_missed_workouts(
    plan: TrainingPlan,
    profile: UserFitnessProfile,
    today: date,
) -> TrainingPlan:
    """Detect missed workouts (past scheduled with no matching activity) and adjust.

    Strategy: if a long run was missed, don't try to make it up —
    just ensure this week's long run isn't too ambitious.
    """
    recent_dates = set()
    for act in profile.recent_activities:
        if hasattr(act.start_time, "date"):
            recent_dates.add(act.start_time.date() if callable(getattr(act.start_time, "date", None)) else str(act.start_time)[:10])

    missed_long_runs = 0
    for week in plan.weeks:
        for workout in week.workouts:
            if (
                workout.scheduled_date
                and workout.scheduled_date < today
                and workout.workout_type == WorkoutType.LONG_RUN
            ):
                workout_date_str = workout.scheduled_date.isoformat()
                if workout_date_str not in {str(d) for d in recent_dates}:
                    missed_long_runs += 1

    # If 2+ long runs missed, reduce next long run distance by 20%
    if missed_long_runs >= 2:
        for week in plan.weeks:
            for workout in week.workouts:
                if (
                    workout.scheduled_date
                    and workout.scheduled_date >= today
                    and workout.workout_type == WorkoutType.LONG_RUN
                ):
                    if workout.estimated_distance_meters:
                        original = workout.estimated_distance_meters
                        workout.estimated_distance_meters = round(original * 0.8)
                        workout.notes += (
                            f" [Reduced from {original/1000:.1f}km due to missed long runs]"
                        )
                    return plan  # Only adjust one

    return plan
