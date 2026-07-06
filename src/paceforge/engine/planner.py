"""Plan generator — converts a fitness profile + goal into a concrete TrainingPlan.

This is the deterministic **scaffold**: it derives exact paces from the athlete's
metrics and fills a periodised, running-only template. It is the canvas, not the
coach. The judgement layer — workout selection, variety, progression, event-specific
structure — is Claude via the ``running-plan`` skill (runs on the user's
subscription), and every plan is gated by ``engine.validate.validate_plan``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from pathlib import Path

import yaml

from paceforge.engine.events import event_profile
from paceforge.engine.vdot import (
    RACE_DISTANCES,
    TrainingPaces,
    normalize_lt_speed,
    paces_from_race,
    paces_from_vdot,
    vdot_from_race,
)
from paceforge.engine.workouts import WorkoutFactory
from paceforge.models.plan import (
    IntensityTarget,
    TrainingPlan,
    TrainingPurpose,
    TrainingWeek,
    Workout,
    WorkoutStep,
    WorkoutStepType,
    WorkoutType,
)
from paceforge.models.profile import GoalType, TrainingGoal, UserFitnessProfile

logger = logging.getLogger(__name__)


def _starting_and_peak_km(
    profile: UserFitnessProfile, goal_type: GoalType, table_peak: float
) -> tuple[float, float]:
    """Anchor plan volume to the athlete's actual mileage, not a fixed table.

    Peak is the greater of the template default and the athlete's current weekly
    mileage scaled by the event's peak factor; start ramps in at ~75% of peak.
    """
    actual = profile.weekly_mileage_km or 0.0
    peak = round(max(table_peak, actual * event_profile(goal_type).peak_km_factor), 1)
    start = round(peak * 0.75, 1)
    return start, peak

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Map goal type + experience to template file
_TEMPLATE_MAP: dict[str, str] = {
    "HALF_MARATHON_beginner": "half_marathon_beginner.yaml",
    "HALF_MARATHON_intermediate": "half_marathon_intermediate.yaml",
    "HALF_MARATHON_advanced": "half_marathon_advanced.yaml",
    "MARATHON_beginner": "marathon_beginner.yaml",
    "MARATHON_intermediate": "marathon_intermediate.yaml",
    "MARATHON_advanced": "marathon_advanced.yaml",
    "HYROX_beginner": "hyrox_beginner.yaml",
    "HYROX_intermediate": "hyrox_intermediate.yaml",
    "HYROX_advanced": "hyrox_advanced.yaml",
    # 5K/10K reuse half-marathon templates with shorter duration
    "5K_beginner": "half_marathon_beginner.yaml",
    "5K_intermediate": "half_marathon_intermediate.yaml",
    "5K_advanced": "half_marathon_intermediate.yaml",
    "10K_beginner": "half_marathon_beginner.yaml",
    "10K_intermediate": "half_marathon_intermediate.yaml",
    "10K_advanced": "half_marathon_advanced.yaml",
}

# ── Workout rotation pools per phase ────────────────────────────────

# Quality session 1: VO2max / speed / hills / fartlek
_Q1_BASE = ["fartlek", "hills", "easy_with_strides", "fartlek"]
_Q1_BUILD = ["vo2max", "speed_400s", "hills", "fartlek"]
_Q1_PEAK = ["vo2max", "speed_400s", "speed_200s", "vo2max"]
_Q1_TAPER = ["easy_with_strides", "speed_200s"]

# Quality session 2: tempo / threshold cruise / progressive / race pace
_Q2_BASE = ["tempo", "progressive", "tempo", "progressive"]
_Q2_BUILD = ["tempo", "threshold_cruise", "progressive", "race_pace"]
_Q2_PEAK = ["threshold_cruise", "race_pace", "tempo", "race_pace"]
_Q2_TAPER = ["tempo", "easy_with_strides"]

# Easy run slot: alternate easy and easy+strides
_EASY_ROTATION = ["easy", "easy_with_strides"]

# Long run slot: alternate types
_LR_BASE = ["long", "long", "long_progressive", "long"]
_LR_BUILD = ["long", "long_progressive", "long_with_race_pace", "long"]
_LR_PEAK = ["long_progressive", "long_with_race_pace", "long_with_race_pace", "long"]
_LR_TAPER = ["long", "long"]

# Compromised-running Q1 rotation (HYROX): running-only run-under-fatigue work —
# 1km repeats at threshold pace mimicking the race's 8x1km, plus VO2max/hills.
# No station or strength sessions: the plan is running only.
_COMPROMISED_Q1_BASE = ["compromised_km", "hills", "compromised_km", "fartlek"]
_COMPROMISED_Q1_BUILD = ["compromised_km", "vo2max", "compromised_km", "hills"]
_COMPROMISED_Q1_PEAK = ["compromised_km", "vo2max", "compromised_km", "compromised_km"]
_COMPROMISED_Q1_TAPER = ["compromised_km", "easy_with_strides"]

# Phase focus descriptions
_FOCUS_BASE = [
    "Aerobic base + running economy",
    "Aerobic base + neuromuscular strides",
    "Aerobic endurance + strength (hills)",
    "Recovery week — maintain aerobic base",
]
_FOCUS_BUILD = [
    "VO2max development + lactate threshold",
    "Speed + sustained tempo effort",
    "Hill power + race-pace specificity",
    "Recovery week — absorb build-phase gains",
]
_FOCUS_PEAK = [
    "VO2max sharpening + race-pace confidence",
    "Speed + threshold tuning",
    "Race-specific rehearsal",
    "Final sharpening",
]
_FOCUS_TAPER = [
    "Volume reduction — maintain intensity",
    "Race week — freshness and confidence",
]


def generate_plan(
    profile: UserFitnessProfile,
    goal: TrainingGoal,
    hyrox_focus: list[str] | None = None,
) -> TrainingPlan:
    """Generate a deterministic template-based training plan.

    Derives training paces from the athlete's metrics and fills a periodised
    template. Smart/adaptive plan design is done by Claude separately (guided by
    the coach skill) and checked by ``engine.validate.validate_plan``.
    """

    # 1. Determine training paces
    paces, pace_source = _derive_paces(profile)
    # Override with user-provided custom paces if given
    if paces and (goal.custom_easy_pace or goal.custom_marathon_pace or goal.custom_threshold_pace):
        paces = TrainingPaces(
            vdot=paces.vdot,
            easy_low=goal.custom_easy_pace or paces.easy_low,
            easy_high=goal.custom_easy_pace or paces.easy_high,
            marathon=goal.custom_marathon_pace or paces.marathon,
            threshold=goal.custom_threshold_pace or paces.threshold,
            interval=paces.interval,
            repetition=paces.repetition,
        )
        pace_source += " + custom overrides"
    elif not paces and (goal.custom_easy_pace or goal.custom_marathon_pace or goal.custom_threshold_pace):
        easy = goal.custom_easy_pace or 360
        marathon = goal.custom_marathon_pace or 300
        threshold = goal.custom_threshold_pace or 270
        paces = TrainingPaces(
            vdot=0,
            easy_low=easy,
            easy_high=easy,
            marathon=marathon,
            threshold=threshold,
            interval=threshold - 20,
            repetition=threshold - 40,
        )
        pace_source = "Custom paces (manual input)"

    # Build athlete summary for plan context
    athlete_summary = _build_athlete_summary(profile, pace_source)

    # 2. Fill the periodised template with derived paces.
    return _generate_template_plan(profile, goal, paces, pace_source=pace_source,
                                   athlete_summary=athlete_summary)


def _generate_template_plan(
    profile: UserFitnessProfile,
    goal: TrainingGoal,
    paces: TrainingPaces | None,
    *,
    pace_source: str = "",
    athlete_summary: str = "",
) -> TrainingPlan:
    """Fill the periodised, running-only template with derived paces."""

    template = _load_template(goal)
    level = (goal.experience_level or _estimate_level(profile)).value

    total_weeks = template["total_weeks"]
    race_date = goal.target_date
    if goal.start_date:
        plan_start = goal.start_date
        plan_start = plan_start - timedelta(days=plan_start.weekday())
        available_weeks = (race_date - plan_start).days // 7
        total_weeks = min(total_weeks, max(available_weeks, 4))
    else:
        plan_start = race_date - timedelta(weeks=total_weeks)
        plan_start = plan_start - timedelta(days=plan_start.weekday())

    table_peak = template["peak_weekly_km"].get(level, template["peak_weekly_km"]["intermediate"])
    _, peak_km = _starting_and_peak_km(profile, goal.goal_type, table_peak)
    volume_prog = template["volume_progression"]

    phase_map: dict[int, str] = {}
    for p in template.get("phases", []):
        for wk in p["weeks"]:
            phase_map[wk] = p["name"]

    # Position of each week within its phase → a 0..1 progression fraction that
    # drives week-over-week overload of the quality sessions.
    week_phase = [phase_map.get(i + 1, "Build") for i in range(total_weeks)]
    phase_positions: dict[str, list[int]] = {}
    for i, ph in enumerate(week_phase):
        phase_positions.setdefault(ph, []).append(i)

    compromised = event_profile(goal.goal_type).compromised_bias
    factory = WorkoutFactory(paces)

    weeks: list[TrainingWeek] = []
    for wk_idx in range(total_weeks):
        wk_num = wk_idx + 1
        week_start = plan_start + timedelta(weeks=wk_idx)
        multiplier = volume_prog[wk_idx] if wk_idx < len(volume_prog) else volume_prog[-1]
        week_km = round(peak_km * multiplier, 1)
        phase = phase_map.get(wk_num, "Build")

        is_race_week = wk_num == total_weeks and "race_week" in template
        if is_race_week:
            day_templates = template["race_week"]
            workouts = _build_workouts(
                day_templates=day_templates,
                week_start=week_start,
                week_km=week_km,
                paces=paces,
                long_run_day=goal.long_run_day,
            )
            # Running-only: drop any hybrid/station race-week entries (e.g. the
            # HYROX race-day sim). The race itself is the plan's target_date.
            workouts = [
                w for w in workouts
                if w.workout_type not in (WorkoutType.HYROX_MIXED, WorkoutType.CROSS_TRAINING)
            ]
            for w in workouts:
                if w.workout_type != WorkoutType.REST and w.purpose is None:
                    w.purpose = TrainingPurpose.RECOVERY
            weeks.append(TrainingWeek(
                week_number=wk_num, phase=phase, total_distance_km=week_km,
                workouts=workouts, focus="Race week — trust the training",
            ))
            continue

        members = phase_positions[week_phase[wk_idx]]
        phase_frac = members.index(wk_idx) / max(len(members) - 1, 1)
        workouts = _build_varied_week(
            factory=factory, phase=phase, week_km=week_km,
            week_start=week_start, wk_idx=wk_idx,
            long_run_day=goal.long_run_day,
            max_days=goal.max_days_per_week,
            training_days=goal.training_days,
            compromised=compromised,
            frac=phase_frac,
        )
        focus = _get_focus(phase, wk_idx)
        actual_km = round(sum(
            (w.estimated_distance_meters or 0) / 1000
            for w in workouts
            if w.workout_type != WorkoutType.REST
        ), 1)
        weeks.append(TrainingWeek(
            week_number=wk_num, phase=phase, total_distance_km=actual_km or week_km,
            workouts=workouts, focus=focus,
        ))

    return TrainingPlan(
        plan_id=str(uuid.uuid4())[:8],
        name=template["name"],
        goal_type=goal.goal_type.value,
        target_date=goal.target_date,
        target_time_seconds=goal.target_time_seconds,
        total_weeks=total_weeks,
        weeks=weeks,
        easy_pace=paces.easy_low if paces else None,
        marathon_pace=paces.marathon if paces else None,
        threshold_pace=paces.threshold if paces else None,
        interval_pace=paces.interval if paces else None,
        repetition_pace=paces.repetition if paces else None,
        vdot=paces.vdot if paces else None,
        pace_source=pace_source,
        athlete_summary=athlete_summary,
    )


def _get_focus(phase: str, wk_idx: int) -> str:
    """Get a focus string for the week based on phase and rotation index."""
    pool = {
        "Base": _FOCUS_BASE,
        "Build": _FOCUS_BUILD,
        "Peak": _FOCUS_PEAK,
        "Taper": _FOCUS_TAPER,
    }.get(phase, _FOCUS_BUILD)
    return pool[wk_idx % len(pool)]


def _build_varied_week(
    factory: WorkoutFactory,
    phase: str,
    week_km: float,
    week_start: date,
    wk_idx: int,
    long_run_day: str,
    max_days: int = 5,
    training_days: list[str] | None = None,
    compromised: bool = False,
    frac: float = 0.0,
) -> list[Workout]:
    """Build a week of running workouts distributed across chosen training days.

    If *training_days* is provided the workouts are placed on those exact days;
    otherwise a backwards-compatible default is derived from *max_days*.
    *compromised* (HYROX) swaps the Q1 pool for run-under-fatigue 1km repeats;
    *frac* (0..1, position within the phase) drives week-over-week overload of the
    quality sessions. The plan is running only — no station/strength sessions.
    """
    from paceforge.models.profile import default_training_days as _default_days

    days = training_days or _default_days(max_days)
    num_run_days = len(days)

    # ── Distance allocation ──────────────────────────────────────────
    long_frac = 0.35
    q1_frac = 0.15
    q2_frac = 0.17

    long_km = round(week_km * long_frac, 1)
    q1_km = round(week_km * q1_frac, 1)
    q2_km = round(week_km * q2_frac, 1)

    easy_slots = max(num_run_days - 3, 1)  # long + q1 + q2 = 3 "core" slots
    remaining_frac = max(1 - long_frac - q1_frac - q2_frac, 0.1)
    per_easy_km = round(week_km * remaining_frac / easy_slots, 1)

    # ── Pick workout types from rotation pools ───────────────────────
    if compromised:
        q1_pool = {
            "Base": _COMPROMISED_Q1_BASE, "Build": _COMPROMISED_Q1_BUILD,
            "Peak": _COMPROMISED_Q1_PEAK, "Taper": _COMPROMISED_Q1_TAPER,
        }.get(phase, _COMPROMISED_Q1_BUILD)
    else:
        q1_pool = {
            "Base": _Q1_BASE, "Build": _Q1_BUILD, "Peak": _Q1_PEAK, "Taper": _Q1_TAPER,
        }.get(phase, _Q1_BUILD)
    q2_pool = {
        "Base": _Q2_BASE, "Build": _Q2_BUILD, "Peak": _Q2_PEAK, "Taper": _Q2_TAPER,
    }.get(phase, _Q2_BUILD)
    lr_pool = {
        "Base": _LR_BASE, "Build": _LR_BUILD, "Peak": _LR_PEAK, "Taper": _LR_TAPER,
    }.get(phase, _LR_BUILD)

    q1_type = q1_pool[wk_idx % len(q1_pool)]
    q2_type = q2_pool[wk_idx % len(q2_pool)]
    lr_type = lr_pool[wk_idx % len(lr_pool)]
    easy_type = _EASY_ROTATION[wk_idx % len(_EASY_ROTATION)]

    # ── Assign roles to training days ────────────────────────────────
    sorted_days = sorted(days, key=lambda d: _DAY_OFFSETS[d])
    role_map: dict[str, str] = {}

    # 1. Long run
    lr_day = long_run_day if long_run_day in sorted_days else sorted_days[-1]
    role_map[lr_day] = "long_run"

    # 2. Place Q1 and Q2 with maximum separation (not calendar-adjacent)
    remaining = [d for d in sorted_days if d not in role_map]
    if len(remaining) >= 2:
        best_q1, best_q2 = remaining[0], remaining[-1]
        max_gap = 0
        for i, d1 in enumerate(remaining):
            for d2 in remaining[i + 1:]:
                gap = _DAY_OFFSETS[d2] - _DAY_OFFSETS[d1]
                if gap > max_gap and gap > 1:
                    max_gap = gap
                    best_q1, best_q2 = d1, d2
        if max_gap == 0:
            best_q1, best_q2 = remaining[0], remaining[-1]
        role_map[best_q1] = "q1"
        role_map[best_q2] = "q2"
    elif len(remaining) == 1:
        role_map[remaining[0]] = "q1"

    # 3. Fill remaining training days with easy runs
    easy_idx = 0
    for d in sorted_days:
        if d not in role_map:
            role_map[d] = f"easy_{easy_idx}"
            easy_idx += 1

    # ── Generate all 7 days ──────────────────────────────────────────
    all_day_names = list(_DAY_OFFSETS.keys())
    training_set = set(days)
    workouts: list[Workout] = []

    for offset in range(7):
        day_name = all_day_names[offset]
        workout_date = week_start + timedelta(days=offset)

        if day_name not in training_set:
            continue  # non-training days are implicit rest — no placeholder entry

        role = role_map.get(day_name, "easy_0")

        if role == "long_run":
            w = _make_long_run(factory, lr_type, long_km)
        elif role == "q1":
            w = _make_q1(factory, q1_type, q1_km, frac)
        elif role == "q2":
            w = _make_q2(factory, q2_type, q2_km, frac)
        else:
            if easy_type == "easy_with_strides":
                w = factory.easy_with_strides(per_easy_km)
            else:
                w = factory.easy_run(per_easy_km)

        w.scheduled_date = workout_date
        workouts.append(w)

    return workouts


def _bump(base: int, frac: float, span: int) -> int:
    """Overload a rep count by up to *span* across a phase (frac 0..1)."""
    return base + round(frac * span)


def _make_q1(factory: WorkoutFactory, q1_type: str, distance_km: float,
             frac: float = 0.0) -> Workout:
    """Generate quality session 1; *frac* (0..1) overloads it across the phase."""
    if q1_type == "vo2max":
        return factory.vo2max_intervals(reps=_bump(5, frac, 2), rep_min=3.5)
    elif q1_type == "compromised_km":
        # HYROX run-under-fatigue: 1km repeats at threshold, growing toward the
        # race's 8x1km as the phase progresses.
        return factory.race_pace_intervals(reps=_bump(5, frac, 3), rep_km=1.0,
                                           pace_key="threshold")
    elif q1_type == "speed_400s":
        return factory.speed_400s(reps=_bump(8, frac, 4))
    elif q1_type == "speed_200s":
        return factory.speed_200s(reps=_bump(10, frac, 4))
    elif q1_type == "hills":
        return factory.hills(reps=_bump(8, frac, 4))
    elif q1_type == "fartlek":
        return factory.fartlek(total_min=_bump(40, frac, 10))
    elif q1_type == "easy_with_strides":
        return factory.easy_with_strides(distance_km)
    else:
        return factory.fartlek(total_min=_bump(40, frac, 10))


def _make_q2(factory: WorkoutFactory, q2_type: str, distance_km: float,
             frac: float = 0.0) -> Workout:
    """Generate quality session 2; *frac* (0..1) overloads it across the phase."""
    if q2_type == "tempo":
        tempo_km = max(distance_km - 3, 3) + frac * 2
        return factory.tempo(tempo_km)
    elif q2_type == "threshold_cruise":
        return factory.threshold_cruise_intervals(reps=_bump(4, frac, 2), rep_min=6)
    elif q2_type == "progressive":
        return factory.progressive_run(distance_km)
    elif q2_type == "race_pace":
        return factory.race_pace_intervals(reps=_bump(4, frac, 2), rep_km=1.0,
                                           pace_key="marathon")
    elif q2_type == "easy_with_strides":
        return factory.easy_with_strides(distance_km)
    else:
        return factory.tempo(max(distance_km - 3, 3) + frac * 2)


def _make_long_run(factory: WorkoutFactory, lr_type: str, distance_km: float) -> Workout:
    """Generate long run based on rotation type."""
    if lr_type == "long_progressive":
        return factory.long_run_progressive(distance_km)
    elif lr_type == "long_with_race_pace":
        return factory.long_run_with_race_pace(distance_km, race_pace_km=min(4, distance_km * 0.25))
    else:
        return factory.long_run(distance_km)


def _derive_paces(profile: UserFitnessProfile) -> tuple[TrainingPaces | None, str]:
    """Get training paces from the best available data source.

    Returns (paces, source_description).

    Priority:
    1. VO2 max (Garmin estimate — most reliable, directly maps to VDOT)
    2. Personal records (actual race results — high confidence)
    3. Race predictions (Garmin estimates)
    4. Lactate threshold speed (requires unit normalization — fallback)
    5. Recent activity fastest pace (rough VDOT estimate)
    """
    # Tier 1: VO2 max directly (most reliable — matches Daniels VDOT)
    if profile.vo2_max:
        source = f"Garmin VO2 Max ({profile.vo2_max:.1f})"
        logger.info("Deriving paces from VO2 max (%.1f)", profile.vo2_max)
        return paces_from_vdot(profile.vo2_max), source

    # Tier 2: Personal records (actual race results)
    for pr in profile.personal_records:
        dist = RACE_DISTANCES.get(pr.distance)
        if dist and pr.time_seconds > 0:
            paces = paces_from_race(dist, pr.time_seconds)
            mins, secs = divmod(int(pr.time_seconds), 60)
            hrs, mins = divmod(mins, 60)
            time_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            source = f"Personal record ({pr.distance} in {time_str} → VDOT {paces.vdot:.1f})"
            logger.info("Deriving paces from personal record (%s)", pr.distance)
            return paces, source

    # Tier 3: Race predictions
    for pred in profile.race_predictions:
        dist = RACE_DISTANCES.get(pred.distance)
        if dist and pred.predicted_seconds > 0:
            paces = paces_from_race(dist, pred.predicted_seconds)
            source = f"Garmin race prediction ({pred.distance} → VDOT {paces.vdot:.1f})"
            logger.info("Deriving paces from race prediction (%s)", pred.distance)
            return paces, source

    # Tier 4: Lactate threshold speed (normalize units first)
    lt_speed = normalize_lt_speed(profile.lactate_threshold_speed)
    if lt_speed:
        lt_distance = lt_speed * 3600
        vdot = vdot_from_race(lt_distance, 3600)
        pace_sec_km = 1000 / lt_speed
        pm, ps = divmod(int(pace_sec_km), 60)
        source = f"Lactate threshold speed ({pm}:{ps:02d}/km → VDOT {vdot:.1f})"
        logger.info("Deriving paces from lactate threshold speed (VDOT=%.1f)", vdot)
        return paces_from_vdot(vdot), source

    # Tier 5: Recent activity fastest pace → rough VDOT estimate
    running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km]
    if running:
        fastest = min(running, key=lambda a: a.avg_pace_sec_per_km or 999)
        if fastest.avg_pace_sec_per_km and fastest.distance_meters > 2000:
            paces = paces_from_race(fastest.distance_meters, fastest.duration_seconds)
            pm, ps = divmod(int(fastest.avg_pace_sec_per_km), 60)
            source = f"Fastest recent activity ({pm}:{ps:02d}/km → VDOT {paces.vdot:.1f})"
            logger.info("Deriving paces from fastest recent activity")
            return paces, source

    return None, "No data available"


def _estimate_level(profile: UserFitnessProfile):
    """Estimate experience level from weekly mileage."""
    from paceforge.models.profile import ExperienceLevel

    km = profile.weekly_mileage_km or 0
    if km >= 50:
        return ExperienceLevel.ADVANCED
    elif km >= 25:
        return ExperienceLevel.INTERMEDIATE
    return ExperienceLevel.BEGINNER


def _build_athlete_summary(profile: UserFitnessProfile, pace_source: str) -> str:
    """Build a readable summary of the athlete data used for the plan."""
    parts = []
    if profile.vo2_max:
        parts.append(f"VO2 Max: {profile.vo2_max:.1f}")
    if profile.resting_hr:
        parts.append(f"Resting HR: {profile.resting_hr} bpm")
    if profile.max_hr:
        parts.append(f"Max HR: {profile.max_hr} bpm")
    if profile.weekly_mileage_km:
        parts.append(f"Weekly mileage: {profile.weekly_mileage_km:.1f} km")
    if profile.training_status:
        parts.append(f"Training status: {profile.training_status}")
    if profile.lactate_threshold_speed and profile.lactate_threshold_speed > 0:
        lt_speed = normalize_lt_speed(profile.lactate_threshold_speed)
        if lt_speed:
            pace_sec_km = 1000 / lt_speed
            pm, ps = divmod(int(pace_sec_km), 60)
            parts.append(f"LT pace: {pm}:{ps:02d}/km")
    if profile.lactate_threshold_hr:
        parts.append(f"LT HR: {profile.lactate_threshold_hr:.0f} bpm")
    if profile.endurance_score:
        parts.append(f"Endurance score: {profile.endurance_score}")
    if profile.weight_kg:
        parts.append(f"Weight: {profile.weight_kg} kg")
    running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km]
    if running:
        avg_dist = sum(a.distance_meters for a in running) / len(running) / 1000
        avg_pace = sum(a.avg_pace_sec_per_km for a in running if a.avg_pace_sec_per_km) / len(running)
        pm, ps = divmod(int(avg_pace), 60)
        parts.append(f"Recent runs: {len(running)} activities, avg {avg_dist:.1f}km @ {pm}:{ps:02d}/km")
    if profile.race_predictions:
        rp_parts = []
        for rp in profile.race_predictions:
            mins, secs = divmod(int(rp.predicted_seconds), 60)
            hrs, mins = divmod(mins, 60)
            time_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            rp_parts.append(f"{rp.distance}: {time_str}")
        parts.append(f"Race predictions: {', '.join(rp_parts)}")
    if profile.personal_records:
        pr_parts = []
        for pr in profile.personal_records:
            mins, secs = divmod(int(pr.time_seconds), 60)
            hrs, mins = divmod(mins, 60)
            time_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            pr_parts.append(f"{pr.distance}: {time_str}")
        parts.append(f"Personal records: {', '.join(pr_parts)}")
    parts.append(f"Pace source: {pace_source}")
    return " · ".join(parts)


def _load_template(goal: TrainingGoal) -> dict:
    level = (
        goal.experience_level.value
        if goal.experience_level
        else "intermediate"
    )
    key = f"{goal.goal_type.value}_{level}"
    filename = _TEMPLATE_MAP.get(key)
    if not filename:
        # Default to half marathon
        filename = "half_marathon_intermediate.yaml"

    path = TEMPLATES_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


_DAY_OFFSETS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _build_workouts(
    day_templates: list[dict],
    week_start: date,
    week_km: float,
    paces: TrainingPaces | None,
    long_run_day: str,
    max_days: int = 5,
) -> list[Workout]:
    workouts: list[Workout] = []

    for day_tmpl in day_templates:
        day_name = day_tmpl["day"]
        offset = _DAY_OFFSETS.get(day_name, 0)
        workout_date = week_start + timedelta(days=offset)

        wtype = WorkoutType(day_tmpl["type"])

        if wtype == WorkoutType.REST:
            continue  # non-training days are implicit rest — no placeholder entry

        # Compute distance
        distance_km = day_tmpl.get("distance_km")
        if not distance_km and "fraction_of_weekly" in day_tmpl:
            distance_km = round(week_km * day_tmpl["fraction_of_weekly"], 1)

        distance_m = (distance_km or 0) * 1000

        # Build steps
        steps = _build_steps(day_tmpl.get("steps", []), paces)

        # Estimate duration from distance + easy pace
        est_duration = None
        if distance_km and paces:
            est_duration = distance_km * paces.easy_low

        workouts.append(
            Workout(
                workout_type=wtype,
                name=day_tmpl.get("description", wtype.value.replace("_", " ").title()),
                description=day_tmpl.get("description", ""),
                scheduled_date=workout_date,
                estimated_duration_seconds=est_duration,
                estimated_distance_meters=distance_m,
                steps=steps,
                notes=day_tmpl.get("notes", ""),
            )
        )

    return workouts


def _build_steps(
    step_defs: list[dict],
    paces: TrainingPaces | None,
) -> list[WorkoutStep]:
    steps: list[WorkoutStep] = []
    for sd in step_defs:
        stype = WorkoutStepType(sd["type"]) if sd["type"] != "repeat" else WorkoutStepType.INTERVAL

        duration_sec = sd.get("duration_min", 0) * 60 if "duration_min" in sd else None
        distance_m = sd.get("distance_km", 0) * 1000 if "distance_km" in sd else None

        # Resolve pace targets
        target_type = IntensityTarget.OPEN
        target_low = None
        target_high = None
        if paces and "pace" in sd:
            target_type = IntensityTarget.PACE
            pace_key = sd["pace"]
            if pace_key == "easy":
                target_low = paces.easy_low
                target_high = paces.easy_high
            elif pace_key == "marathon":
                target_low = paces.marathon - 3
                target_high = paces.marathon + 3
            elif pace_key == "threshold":
                target_low = paces.threshold - 3
                target_high = paces.threshold + 3
            elif pace_key == "interval":
                target_low = paces.interval - 3
                target_high = paces.interval + 3
            elif pace_key == "repetition":
                target_low = paces.repetition - 3
                target_high = paces.repetition + 3

        # Handle repeat groups
        if sd["type"] == "repeat":
            sub_steps = _build_steps(sd.get("steps", []), paces)
            steps.append(
                WorkoutStep(
                    step_type=WorkoutStepType.INTERVAL,
                    description=sd.get("description", f"Repeat x{sd.get('count', 1)}"),
                    repeat_count=sd.get("count", 1),
                    steps=sub_steps,
                )
            )
        else:
            steps.append(
                WorkoutStep(
                    step_type=stype,
                    description=sd.get("description", ""),
                    duration_seconds=duration_sec,
                    distance_meters=distance_m,
                    target_type=target_type,
                    target_low=target_low,
                    target_high=target_high,
                )
            )

    return steps
