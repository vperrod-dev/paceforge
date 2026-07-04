"""Plan-vs-actual compliance — TrainingPeaks-style per-workout bands.

Fills each workout's ``completion_metrics`` from its matched activity, and rolls
weeks up into a compliance summary. Bands (on the primary ratio — distance for
runs, duration for HYROX/cross-training where station work skews distance):

    green   80–120 %      did the session as planned
    yellow  50–79 / 121–150 %   meaningfully short or long
    orange  outside ±50 %       barely related to the plan
    red     scheduled in the past, no matching activity
    (pending = scheduled today or later, not yet done)

Unplanned activities (no workout claimed them) are listed per week as ``grey``.
"""
from __future__ import annotations

from datetime import date

from paceforge.models.plan import TrainingPlan
from paceforge.models.profile import RecentActivity

_DURATION_FIRST = {"hyrox_mixed", "cross_training"}


def _band(ratio: float) -> str:
    pct = ratio * 100
    if 80 <= pct <= 120:
        return "green"
    if 50 <= pct < 80 or 120 < pct <= 150:
        return "yellow"
    return "orange"


def _workout_metrics(wo, acts_by_id: dict[int, RecentActivity], today: date) -> dict | None:
    """completion_metrics for one workout (None when nothing to say yet)."""
    act = next((acts_by_id[a] for a in wo.matched_activity_ids if a in acts_by_id), None)
    if act is None:
        if wo.scheduled_date and wo.scheduled_date < today and not wo.completed:
            return {"status": "red", "reason": "missed"}
        return None

    planned_km = round(wo.estimated_distance_meters / 1000, 2) if wo.estimated_distance_meters else None
    actual_km = round((act.distance_meters or 0) / 1000, 2) or None
    planned_min = round(wo.estimated_duration_seconds / 60, 1) if wo.estimated_duration_seconds else None
    actual_min = round((act.duration_seconds or 0) / 60, 1) or None

    duration_first = str(wo.workout_type) in _DURATION_FIRST
    if duration_first and planned_min and actual_min:
        ratio = actual_min / planned_min
    elif not duration_first and planned_km and actual_km:
        ratio = actual_km / planned_km
    elif planned_min and actual_min:  # fall back to whichever pair exists
        ratio = actual_min / planned_min
    elif planned_km and actual_km:
        ratio = actual_km / planned_km
    else:
        return {"status": "green", "reason": "completed (no planned volume to compare)",
                "actual_km": actual_km, "actual_min": actual_min}

    return {
        "status": _band(ratio),
        "ratio": round(ratio, 2),
        "planned_km": planned_km, "actual_km": actual_km,
        "planned_min": planned_min, "actual_min": actual_min,
        "activity_id": act.activity_id,
    }


def annotate_plan(plan: TrainingPlan, activities: list[RecentActivity],
                  today: date | None = None) -> None:
    """Set completion_metrics on every dated workout (mutates the plan in place)."""
    today = today or date.today()
    acts_by_id = {a.activity_id: a for a in activities}
    for wk in plan.weeks:
        for wo in wk.workouts:
            if not wo.scheduled_date or wo.workout_type == "rest":
                continue
            wo.completion_metrics = _workout_metrics(wo, acts_by_id, today)


def weekly_compliance(plan: TrainingPlan, activities: list[RecentActivity],
                      today: date | None = None) -> dict:
    """Roll workouts up into per-week and overall compliance (for fitness.json).

    Only weeks that have started count toward the overall percentage — future
    weeks aren't "non-compliant", they just haven't happened.
    """
    today = today or date.today()
    matched_ids = {aid for wk in plan.weeks for wo in wk.workouts
                   for aid in wo.matched_activity_ids}
    weeks = []
    total_scored = total_green = 0
    for wk in plan.weeks:
        dated = [wo for wo in wk.workouts if wo.scheduled_date and wo.workout_type != "rest"]
        if not dated:
            continue
        week_start = min(wo.scheduled_date for wo in dated)
        week_end = max(wo.scheduled_date for wo in dated)
        if week_start > today:
            continue
        counts = {"green": 0, "yellow": 0, "orange": 0, "red": 0, "pending": 0}
        for wo in dated:
            status = (wo.completion_metrics or {}).get("status")
            counts[status if status in counts else "pending"] += 1
        scored = sum(counts[c] for c in ("green", "yellow", "orange", "red"))
        unplanned = [
            {"activity_id": a.activity_id, "name": a.name, "type": a.activity_type,
             "date": str(a.start_time)[:10]}
            for a in activities
            if a.activity_id not in matched_ids
            and week_start <= a.start_time.date() <= week_end
        ]
        weeks.append({
            "week_number": wk.week_number,
            "start": week_start.isoformat(),
            "counts": counts,
            "compliance_pct": round(100 * counts["green"] / scored) if scored else None,
            "unplanned": unplanned,
        })
        total_scored += scored
        total_green += counts["green"]
    return {
        "weeks": weeks,
        "overall_pct": round(100 * total_green / total_scored) if total_scored else None,
    }
