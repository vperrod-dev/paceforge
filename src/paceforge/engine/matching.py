"""Match completed Garmin activities to scheduled plan workouts.

The matcher was dropped in the serverless rewrite, so nothing populated
Workout.matched_activity_ids and the "planned vs actual" view was always empty.
Runs match by date + nearest distance; HYROX/cross-training slots (where station
work makes distance meaningless) match by date + nearest duration. Matching runs
in passes — runs claim run activities before a mixed slot can steal one.
"""
from __future__ import annotations

from paceforge.models.plan import TrainingPlan
from paceforge.models.profile import RecentActivity

_RUN_TYPES = {"running", "treadmill_running", "track_running", "trail_running"}
_HYROX_TYPES = {"running", "hiit", "cardio", "cardio_training", "indoor_cardio",
                "mixed_cardio", "strength_training", "fitness_equipment", "other"}
_CROSS_TYPES = {"strength_training", "indoor_cardio", "cardio_training", "hiit",
                "cardio", "mixed_cardio", "fitness_equipment", "other",
                # Bikes: Garmin splits cycling into one type per surface.
                "cycling", "indoor_cycling", "virtual_ride", "road_biking",
                "mountain_biking", "gravel_cycling", "cyclocross", "e_bike_fitness"}
# Days a workout can slip and still match — you sometimes run a session a day off.
_DAY_TOLERANCE = 1
# A run only auto-links when its distance is within 90% of the planned distance —
# an unplanned run on a training day must not be mistaken for the session.
_MIN_SIMILARITY = 0.9

# Matching passes, in claim order: (plan workout types, garmin types, criterion).
_PASSES = (
    (None, _RUN_TYPES, "distance"),            # None → any run-shaped workout type
    ({"hyrox_mixed"}, _HYROX_TYPES, "duration"),
    ({"cross_training"}, _CROSS_TYPES, "duration"),
)
_NON_RUN_WORKOUTS = {"hyrox_mixed", "cross_training", "rest"}


def _act_type(act: RecentActivity) -> str:
    return (act.activity_type or "").lower()


def _similarity(actual: float | None, target: float | None) -> float:
    """Size ratio in [0, 1] — 1.0 means identical distance/duration."""
    if not actual or not target:
        return 0.0
    return min(actual, target) / max(actual, target)


def match_plan_to_activities(plan: TrainingPlan, activities: list[RecentActivity],
                             rpe_map: dict | None = None) -> int:
    """Link activities to scheduled workouts, preferring an exact-date match and
    falling back to ±1 day. Each activity matches at most ONE workout.

    Authoritative: clears existing matches first and recomputes, so an activity can
    never end up attached to two workouts. User-pinned links (manual_activity_ids)
    are applied verbatim before the auto passes and never overridden; excluded ids
    are never auto-linked. Runs additionally need >=90% distance similarity.
    Sets matched_activity_ids + completed, and copies any logged RPE onto the
    matched workout. Returns matched count.
    """
    workouts = sorted(
        (wo for wk in plan.weeks for wo in wk.workouts
         if wo.scheduled_date and wo.workout_type != "rest"),
        key=lambda wo: wo.scheduled_date,
    )
    for wo in workouts:
        wo.matched_activity_ids = []
        wo.completed = False

    used: set[int] = set()
    matched = 0
    for wo in workouts:
        if wo.manual_activity_ids:
            wo.matched_activity_ids = list(wo.manual_activity_ids)
            wo.completed = True
            used.update(wo.manual_activity_ids)
            matched += 1

    # Exact date first (tol=0), then ±1 day — so a session lands on its own day
    # before a neighbouring workout of ANY type can claim it. Tolerance outranks
    # pass order: a ±1-day hyrox slot must not steal today's cardio from today's
    # cross-training slot.
    for tol in (0, _DAY_TOLERANCE):
        for wo_types, act_types, criterion in _PASSES:
            slots = [wo for wo in workouts
                     if (str(wo.workout_type) in wo_types if wo_types
                         else str(wo.workout_type) not in _NON_RUN_WORKOUTS)]
            pool = [a for a in activities if _act_type(a) in act_types]
            for wo in slots:
                if wo.matched_activity_ids:
                    continue
                candidates = [
                    a for a in pool
                    if a.activity_id not in used
                    and a.activity_id not in wo.excluded_activity_ids
                    and abs((a.start_time.date() - wo.scheduled_date).days) <= tol
                ]
                if not candidates:
                    continue
                if criterion == "distance":
                    target = wo.estimated_distance_meters
                    best = max(candidates,
                               key=lambda a: _similarity(a.distance_meters, target))
                    if _similarity(best.distance_meters, target) < _MIN_SIMILARITY:
                        continue
                else:
                    target = wo.estimated_duration_seconds or 0
                    best = min(candidates,
                               key=lambda a: abs((a.duration_seconds or 0) - target))
                used.add(best.activity_id)
                wo.matched_activity_ids = [best.activity_id]
                wo.completed = True
                matched += 1

    if rpe_map:
        for wo in workouts:
            for aid in wo.matched_activity_ids:
                entry = rpe_map.get(aid)
                if entry and entry.get("rpe"):
                    wo.user_rpe = int(entry["rpe"])
    return matched
