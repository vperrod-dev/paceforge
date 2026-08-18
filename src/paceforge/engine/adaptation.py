"""Plan adaptation — adjust upcoming workouts based on completed activity data."""

from __future__ import annotations

from datetime import date, timedelta

from paceforge.models.plan import TrainingPlan, Workout, WorkoutType


def reflow_missed_sessions(plan: TrainingPlan, today: date | None = None,
                           busy_dates: set[date] | None = None) -> list[str]:
    """Move this week's missed quality session into a later easy slot, same week.

    No "punishment" catch-up: one missed quality session moves forward onto an
    easy day if the spacing rules survive; if the week has no safe slot it is
    simply dropped (the note records that). Never stacks two hard days.
    *busy_dates* are days the athlete already has a booked session on
    (``data/calendar.json``) — the plan does not get to drop a hard run on top
    of a class it did not schedule. Mutates the plan in place; returns
    human-readable change descriptions.
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
        booked = busy_dates or set()
        for missed in dated:
            if not (_is_missed(missed, today) and missed.workout_type in INTENSE_TYPES):
                continue
            slot = next(
                (w for w in dated
                 if w.scheduled_date > today
                 and w.workout_type in (WorkoutType.EASY_RUN, WorkoutType.RECOVERY)
                 and w.scheduled_date not in booked
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


def hold_back_progression(plan: TrainingPlan, today: date | None = None) -> list[str]:
    """Repeat, don't advance: a failed quality session holds its flavor's
    progression instead of stepping up next time.

    Looks at last week's quality workouts (by ``variant_key`` slot:flavor:index).
    Failed = compliance status red, missed entirely, or rated RPE >= 9. The next
    scheduled workout of the same slot+flavor at a HIGHER index is replaced by a
    copy of the failed session (fresh id/date, completion state reset). Long runs
    and the taper are never touched; conservative by design.
    """
    today = today or date.today()
    changes: list[str] = []
    week_ago = today - timedelta(days=7)

    failed: dict[str, Workout] = {}
    for week in plan.weeks:
        for w in week.workouts:
            if not (w.variant_key and w.scheduled_date
                    and week_ago <= w.scheduled_date < today):
                continue
            status = (w.completion_metrics or {}).get("status")
            if (status == "red" or (w.user_rpe or 0) >= 9
                    or (not w.completed and w.scheduled_date < today)):
                slot_flavor = ":".join(w.variant_key.split(":")[:2])
                failed[slot_flavor] = w

    if not failed:
        return changes

    for week in plan.weeks:
        if week.phase == "Taper":
            continue
        for i, w in enumerate(week.workouts):
            if not (w.variant_key and w.scheduled_date and w.scheduled_date >= today):
                continue
            parts = w.variant_key.split(":")
            slot_flavor = ":".join(parts[:2])
            prior = failed.get(slot_flavor)
            if prior is None:
                continue
            prior_idx = int(prior.variant_key.split(":")[2])
            if int(parts[2]) <= prior_idx:
                continue
            repeat = prior.model_copy(deep=True)
            repeat.session_id = w.session_id           # keep the calendar slot's id
            repeat.scheduled_date = w.scheduled_date
            repeat.completed = False
            repeat.completion_metrics = None
            repeat.completion_analysis = None
            repeat.matched_activity_ids = []
            repeat.manual_activity_ids = []
            repeat.excluded_activity_ids = []
            repeat.user_rpe = None
            repeat.garmin_workout_id = w.garmin_workout_id  # re-push overwrites by id
            repeat.variant_key = prior.variant_key
            repeat.notes = ("[Repeated — last attempt didn't land; advance next time] "
                            + (prior.notes or "")).strip()
            week.workouts[i] = repeat
            changes.append(
                f"Held back {w.name} on {w.scheduled_date} — repeating "
                f"{prior.name} (last attempt didn't land)"
            )
            del failed[slot_flavor]   # hold back one occurrence, not the whole plan
    return changes


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
                    session_id=workout.session_id,
                    garmin_workout_id=workout.garmin_workout_id,
                )
                return [f"Downgraded {workout.name} on {workout.scheduled_date} to easy — {reason}"]
    return []
