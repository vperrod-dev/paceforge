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


# ── Pace insights (Runna-style) ──────────────────────────────────────
# Quality sessions only — did the athlete run the work inside the target
# window? Feeds the accept/reject pace-recalibration loop.

_PACE_QUALITY = {
    "tempo", "threshold", "race_pace", "vo2max", "speed", "intervals", "progressive",
}


def _work_window(wo) -> tuple[float, float, float] | None:  # noqa: ANN001
    """(low, high, work_km) across the workout's paced work steps."""
    lows: list[float] = []
    highs: list[float] = []
    work_km = 0.0
    for step in wo.steps:
        subs = step.steps if step.steps else [step]
        mult = step.repeat_count or 1
        for s in subs:
            if s.step_type.value not in ("interval", "active"):
                continue
            if not (s.target_low and s.target_high) or s.pace_key == "easy":
                continue
            lows.append(s.target_low)
            highs.append(s.target_high)
            if s.distance_meters:
                work_km += s.distance_meters / 1000 * mult
            elif s.duration_seconds:
                work_km += s.duration_seconds / ((s.target_low + s.target_high) / 2) * mult
    if not lows or work_km < 0.5:
        return None
    return min(lows), max(highs), work_km


def pace_metrics(wo, detail: dict | None, lt_hr: float | None = None) -> dict | None:  # noqa: ANN001
    """Actual-vs-target pace verdict for one quality workout.

    Uses the fastest-N km splits (N ≈ planned work volume) as the work
    approximation — exact step↔lap alignment deliberately skipped. Paces are
    heat-adjusted before judging; an 'ahead' verdict is withheld when HR says
    the athlete was simply racing the session (pace:HR guard).
    """
    from paceforge.engine.enviro import adjusted_pace

    if str(wo.workout_type) not in _PACE_QUALITY or not detail:
        return None
    window = _work_window(wo)
    if window is None:
        return None
    low, high, work_km = window
    splits = [
        s for s in (detail.get("splits") or [])
        if s.get("pace_sec") and (s.get("distance_m") or 0) > 800
    ]
    n = max(1, round(work_km))
    if len(splits) < n:
        return None
    work_splits = sorted(splits, key=lambda s: s["pace_sec"])[:n]
    raw = sum(s["pace_sec"] for s in work_splits) / n
    actual = adjusted_pace(raw, detail.get("weather")) or raw
    mid = (low + high) / 2
    ahead = actual < low
    if ahead and lt_hr:
        hrs = [s["avg_hr"] for s in work_splits if s.get("avg_hr")]
        if hrs and sum(hrs) / len(hrs) > lt_hr + 5:
            ahead = False  # faster than the window but red-lining — that's racing
    return {
        "pace_actual_sec": round(actual, 1),
        "pace_target_low": round(low, 1),
        "pace_target_high": round(high, 1),
        "pace_delta_sec": round(actual - mid, 1),
        "within_band": low <= actual <= high,
        "ahead": ahead,
    }


def annotate_pace(plan: TrainingPlan, details: dict[int, dict],
                  lt_hr: float | None = None) -> None:
    """Merge pace metrics into completion_metrics for matched quality workouts."""
    for wk in plan.weeks:
        for wo in wk.workouts:
            det = next(
                (details[a] for a in wo.matched_activity_ids if a in details), None
            )
            pm = pace_metrics(wo, det, lt_hr=lt_hr)
            if pm:
                wo.completion_metrics = {**(wo.completion_metrics or {}), **pm}


def pace_status(plan: TrainingPlan, today: date | None = None) -> dict:
    """Roll the last 5 judged quality sessions into a Runna-style status.

    The 5-session window must span ≥3 weeks — at 2 quality sessions a week
    anything shorter is too twitchy to act on.
    """
    today = today or date.today()
    judged = [
        (wo.scheduled_date, wo.completion_metrics)
        for wk in plan.weeks
        for wo in wk.workouts
        if wo.scheduled_date and wo.completion_metrics
        and "pace_delta_sec" in wo.completion_metrics
    ]
    judged.sort(key=lambda t: t[0], reverse=True)
    recent = judged[:5]
    if len(recent) < 5:
        return {"status": "monitoring", "sessions": len(recent)}
    span_days = (recent[0][0] - recent[-1][0]).days
    ahead = sum(1 for _, m in recent if m.get("ahead"))
    slow = sum(
        1 for _, m in recent if not m.get("within_band") and m.get("pace_delta_sec", 0) > 0
    )
    if span_days < 21:
        status = "monitoring"
    elif ahead >= 4:
        status = "ahead"
    elif slow >= 3:
        status = "review"
    else:
        status = "on-point"
    return {
        "status": status,
        "sessions": len(recent),
        "span_days": span_days,
        "ahead": ahead,
        "slow": slow,
        "avg_delta_sec": round(sum(m["pace_delta_sec"] for _, m in recent) / len(recent), 1),
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
                      today: date | None = None, items: list | None = None) -> dict:
    """Roll workouts up into per-week and overall compliance (for fitness.json).

    Only weeks that have started count toward the overall percentage — future
    weeks aren't "non-compliant", they just haven't happened.

    The week is the athlete's WHOLE week: scheduled calendar items (classes,
    rides, swims — `data/calendar.json`) are planned sessions too, so they score
    alongside the running workouts (done = green, past and not done = red) and
    their activities are never listed as ``unplanned``.
    """
    today = today or date.today()
    items = items or []
    matched_ids = {str(aid) for wk in plan.weeks for wo in wk.workouts
                   for aid in wo.matched_activity_ids}
    matched_ids |= {str(aid) for i in items for aid in i.matched_activity_ids}
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
        wk_items = [i for i in items if week_start <= i.date <= week_end]
        for item in wk_items:
            counts["green" if item.completed
                   else "red" if item.date < today else "pending"] += 1
        scored = sum(counts[c] for c in ("green", "yellow", "orange", "red"))
        unplanned = [
            {"activity_id": a.activity_id, "name": a.name, "type": a.activity_type,
             "date": str(a.start_time)[:10]}
            for a in activities
            if str(a.activity_id) not in matched_ids
            and week_start <= a.start_time.date() <= week_end
        ]
        weeks.append({
            "week_number": wk.week_number,
            "start": week_start.isoformat(),
            "counts": counts,
            "compliance_pct": round(100 * counts["green"] / scored) if scored else None,
            "unplanned": unplanned,
            "calendar": [
                {"item_id": i.item_id, "date": i.date.isoformat(), "sport": i.sport,
                 "title": i.title, "duration_min": i.duration_min,
                 "completed": i.completed, "matched_activity_ids": i.matched_activity_ids}
                for i in wk_items
            ],
        })
        total_scored += scored
        total_green += counts["green"]
    return {
        "weeks": weeks,
        "overall_pct": round(100 * total_green / total_scored) if total_scored else None,
    }
