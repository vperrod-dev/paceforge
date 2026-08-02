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

from paceforge.engine.briefings import build_briefing, week_intro
from paceforge.engine.events import event_profile
from paceforge.engine.variants import pick_variant
from paceforge.engine.vdot import (
    RACE_DISTANCES,
    ZONE_KEYS,
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
    peak = max(table_peak, actual * event_profile(goal_type).peak_km_factor)
    if actual:
        # A low-mileage athlete can't absorb the table peak in one plan —
        # cap peak at ~2.2x current load (still a big build), floor at half
        # the table so the plan stays event-credible.
        peak = min(peak, max(actual * 2.2, table_peak * 0.5))
    peak = round(peak, 1)
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
# Phase ordering follows Daniels/Pfitzinger for long events: R/hills/strides
# early (economy), I mid-build, T + race-pace dominate late build and peak,
# R volume DECLINES toward race day.

# Pools are indexed by GLOBAL week index (wk_idx % len), so adjacent weeks read
# adjacent slots — possibly across a phase boundary. Orderings below are chosen
# so no two adjacent slots (including wrap-around and any phase transition)
# carry the same type: the variety gate forbids identical sessions in
# consecutive weeks, and a deload's variant step-back can otherwise reproduce
# last week's exact session.

# Quality session 1: speed / power / VO2 slot
_Q1_BASE = ["hills", "speed_200s", "fartlek", "easy_with_strides"]
_Q1_BUILD = ["vo2max", "speed_400s", "vo2max", "hills"]
_Q1_PEAK = ["vo2max", "speed_200s", "vo2max", "hills"]
_Q1_TAPER = ["easy_with_strides", "speed_200s"]

# Quality session 2: threshold / race-specificity slot
_Q2_BASE = ["tempo", "progressive", "steady_m", "threshold_cruise"]
_Q2_BUILD = ["progressive", "alternations", "tempo", "threshold_cruise"]
_Q2_PEAK = ["alternations", "race_pace", "threshold_cruise", "race_pace"]
_Q2_TAPER = ["tempo", "race_pace"]

# Easy run slot: alternate easy and easy+strides
_EASY_ROTATION = ["easy", "easy_with_strides"]

# Hard long-run subtypes cycled per phase — a hard long run fires every OTHER
# week (odd weeks), so consecutive hard occurrences step through these lists
# and never repeat a subtype back-to-back. Even weeks are unstructured — run
# to feel, no targets — which is what makes the hard ones land (Runna's rule).
_LR_HARD = {
    "Base": ["long_progressive", "long_blocks"],
    "Build": ["long_blocks", "long_progressive", "long_with_race_pace"],
    "Peak": ["long_with_race_pace", "long_blocks", "long_with_race_pace", "long_progressive"],
}


def _long_run_type(phase: str, wk_idx: int, deload: bool, weeks_to_race: int,
                   week_in_phase: int, phase_len: int) -> str:
    """Pick the long-run subtype for a week (C10 rules).

    Cutback weeks and the taper are unstructured; the dress rehearsal
    (race-pace long run) lands ~3 weeks out; otherwise hard subtypes alternate
    with unstructured runs, race-pace only from mid-build.
    """
    if phase == "Taper" or weeks_to_race <= 1:
        return "long"
    if weeks_to_race == 3:
        return "long_with_race_pace"  # dress rehearsal — even on a cutback (fresh legs)
    if deload or wk_idx % 2 == 0:
        return "long"  # unstructured — switch off, run to feel
    hard = _LR_HARD.get(phase, _LR_HARD["Build"])
    pick = hard[(wk_idx // 2) % len(hard)]
    if pick == "long_with_race_pace" and phase == "Build" and week_in_phase < phase_len / 2:
        return "long_progressive"  # race-pace waits until mid-build
    return pick

# Compromised-running Q1 rotation (HYROX): running-only run-under-fatigue work —
# 1km repeats at threshold pace mimicking the race's 8x1km, plus VO2max/hills.
# No station or strength sessions: the plan is running only.
_COMPROMISED_Q1_BASE = ["compromised_km", "hills", "compromised_km", "fartlek"]
_COMPROMISED_Q1_BUILD = ["compromised_km", "vo2max", "compromised_km", "hills"]
_COMPROMISED_Q1_PEAK = ["compromised_km", "vo2max", "compromised_km", "vo2max"]
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

    native_total_weeks = total_weeks = template["total_weeks"]
    race_date = goal.target_date
    # The race-week template schedules "RACE DAY" on a fixed weekday (e.g. Sunday)
    # within the final week, so the final week must be anchored to the Monday of
    # race_date's own week — not derived by subtracting whole weeks from race_date
    # and then Monday-aligning, which silently drops the remainder days and can
    # leave the plan (and its race day) up to 6 days short of the actual target_date.
    race_week_start = race_date - timedelta(days=race_date.weekday())
    # No explicit start_date means "start ASAP" (today), not "no limit on how far
    # back the plan may reach" — without this, a race closer than the template's
    # full length (e.g. HALF_MARATHON's 12 weeks) back-dates week 1 into the past.
    effective_start = goal.start_date or date.today()
    start_monday = effective_start - timedelta(days=effective_start.weekday())
    available_weeks = (race_week_start - start_monday).days // 7 + 1
    total_weeks = min(total_weeks, max(available_weeks, 4))
    plan_start = race_week_start - timedelta(weeks=total_weeks - 1)

    table_peak = template["peak_weekly_km"].get(level, template["peak_weekly_km"]["intermediate"])
    _, peak_km = _starting_and_peak_km(profile, goal.goal_type, table_peak)
    volume_prog = template["volume_progression"]

    phase_map: dict[int, str] = {}
    for p in template.get("phases", []):
        for wk in p["weeks"]:
            phase_map[wk] = p["name"]

    def _template_week(i: int) -> int:
        """Map a compressed-plan week index to the native template's week number,
        so a race closer than the template's own length (clamped total_weeks
        below native_total_weeks) still reaches the template's Peak/Taper weeks
        near the end — instead of just truncating the front of the curve and
        leaving the plan's last week stuck in Base/Build with no taper at all."""
        if total_weeks <= 1:
            return native_total_weeks
        return round(i * (native_total_weeks - 1) / (total_weeks - 1)) + 1

    # Position of each week within its phase → a 0..1 progression fraction that
    # drives week-over-week overload of the quality sessions.
    week_phase = [phase_map.get(_template_week(i), "Build") for i in range(total_weeks)]
    phase_positions: dict[str, list[int]] = {}
    for i, ph in enumerate(week_phase):
        phase_positions.setdefault(ph, []).append(i)

    compromised = event_profile(goal.goal_type).compromised_bias
    last_tt: int | None = None
    goal_pace = None
    goal_dist = RACE_DISTANCES.get(goal.goal_type.value)
    if goal.target_time_seconds and goal_dist:
        goal_pace = goal.target_time_seconds / (goal_dist / 1000)
    factory = WorkoutFactory(paces, goal_pace_sec_km=goal_pace)

    # Anchor early volume to the athlete's actual mileage: cap week 1 near
    # current load and let the cap grow ~12%/week (inside the validate ramp)
    # until the template curve takes over. Deload dips survive via min().
    week_kms = [
        round(peak_km * volume_prog[min(_template_week(i) - 1, len(volume_prog) - 1)], 1)
        for i in range(total_weeks)
    ]
    actual_km = profile.weekly_mileage_km or 0.0
    if actual_km:
        cap = max(actual_km * 1.15, peak_km * 0.35)
        for i in range(total_weeks):
            week_kms[i] = round(min(week_kms[i], cap), 1)
            cap *= 1.12

    weeks: list[TrainingWeek] = []
    for wk_idx in range(total_weeks):
        wk_num = wk_idx + 1
        week_start = plan_start + timedelta(weeks=wk_idx)
        week_km = week_kms[wk_idx]
        # Ramp gate by construction: cap growth at 15% over the previous week's
        # ACTUAL volume (workout sums drift from the planned curve). Rebounds
        # from a cutback are exempt, mirroring validate's rule.
        if len(weeks) >= 1:
            prev = weeks[-1].total_distance_km or week_km
            before = weeks[-2].total_distance_km if len(weeks) >= 2 else None
            if not (before and prev < before):
                week_km = round(min(week_km, prev * 1.15), 1)
        phase = phase_map.get(_template_week(wk_idx), "Build")

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
                w.briefing = build_briefing(w, phase=phase, hyrox=compromised)
            weeks.append(TrainingWeek(
                week_number=wk_num, phase=phase, total_distance_km=week_km,
                workouts=workouts, focus="Race week — trust the training",
                intro=week_intro(phase, 0, 1, False, 0),
            ))
            continue

        members = phase_positions[week_phase[wk_idx]]
        week_in_phase = members.index(wk_idx)
        deload = wk_idx > 0 and week_kms[wk_idx] < week_kms[wk_idx - 1]
        weeks_to_race = total_weeks - wk_num
        lr_type = _long_run_type(
            phase, wk_idx, deload, weeks_to_race, week_in_phase, len(members)
        )
        # Milestone time trial on a deload ≥4 weeks out, ≥4 weeks apart — a
        # maximal effort, so it consumes BOTH quality slots that week.
        tt_km = None
        if deload and weeks_to_race >= 4 and (last_tt is None or wk_idx - last_tt >= 4):
            tt_km = 3.0 if goal.goal_type.value == "5K" else 5.0
            last_tt = wk_idx
        workouts = _build_varied_week(
            factory=factory, phase=phase, week_km=week_km,
            week_start=week_start, wk_idx=wk_idx,
            long_run_day=goal.long_run_day,
            max_days=goal.max_days_per_week,
            training_days=goal.training_days,
            compromised=compromised,
            week_in_phase=week_in_phase,
            deload=deload,
            lr_type=lr_type,
            lr_rehearsal=weeks_to_race == 3,
            time_trial_km=tt_km,
        )
        for w in workouts:
            w.briefing = build_briefing(w, phase=phase, hyrox=compromised)
        focus = _get_focus(phase, wk_idx)
        actual_km = round(sum(
            (w.estimated_distance_meters or 0) / 1000
            for w in workouts
            if w.workout_type != WorkoutType.REST
        ), 1)
        weeks.append(TrainingWeek(
            week_number=wk_num, phase=phase, total_distance_km=actual_km or week_km,
            workouts=workouts, focus=focus,
            intro=week_intro(phase, week_in_phase, len(members), deload, weeks_to_race),
        ))

    pace_bands = {k: list(paces.band(k)) for k in ZONE_KEYS} if paces else None
    if pace_bands is not None and goal_pace:
        pace_bands["race"] = [goal_pace * 0.985, goal_pace * 1.03]

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
        pace_bands=pace_bands,
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
    week_in_phase: int = 0,
    deload: bool = False,
    lr_type: str = "long",
    lr_rehearsal: bool = False,
    time_trial_km: float | None = None,
) -> list[Workout]:
    """Build a week of running workouts distributed across chosen training days.

    If *training_days* is provided the workouts are placed on those exact days;
    otherwise a backwards-compatible default is derived from *max_days*.
    *compromised* (HYROX) swaps the Q1 pool for run-under-fatigue 1km repeats;
    *week_in_phase* walks each slot's variant table forward (Canova-lever
    progression) and *deload* steps it back one. The plan is running only —
    no station/strength sessions.
    """
    from paceforge.models.profile import default_training_days as _default_days

    days = training_days or _default_days(max_days)
    num_run_days = len(days)

    # ── Distance allocation — frequency-aware ────────────────────────
    # At 3 run days the long run legitimately carries more of the week (the
    # endurance requirement doesn't shrink because frequency did); at 5+ the
    # classic ~30% split applies.
    if num_run_days <= 3:
        long_frac, q1_frac, q2_frac = 0.45, 0.25, 0.30
    elif num_run_days == 4:
        long_frac, q1_frac, q2_frac = 0.38, 0.18, 0.20
    else:
        long_frac, q1_frac, q2_frac = 0.32, 0.15, 0.17

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

    q1_type = q1_pool[wk_idx % len(q1_pool)]
    q2_type = q2_pool[wk_idx % len(q2_pool)]
    easy_type = _EASY_ROTATION[wk_idx % len(_EASY_ROTATION)]

    # Skeleton density: at ≤3 run days a hard long-run subtype consumes a
    # quality slot — the week is (Q1 + easy + hard long), never Q1+Q2+hard long,
    # or the athlete gets zero easy running. A time trial is maximal effort and
    # likewise strips the second quality session.
    demote_q2 = (num_run_days <= 3 and lr_type != "long") or time_trial_km is not None

    # Low-volume weeks (ACWR anchor biting): hard Q1 doesn't fit the budget —
    # keep the stimulus mild until volume supports real quality work.
    # ponytail: blunt threshold; PR3's variant volume-gating generalizes this.
    if week_km < 25 and q1_type not in ("easy_with_strides",):
        q1_type = "easy_with_strides"

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
    # Quality sessions carry fixed overhead (warmup/cooldown) that can overshoot
    # their nominal budget, so build them first and give the easy days the
    # actual remainder — keeps the week's true volume at week_km.
    # Strides bolt-on: in Build/Peak the easy day just before Q1 primes the legs.
    strides_day = None
    if phase in ("Build", "Peak"):
        q1_day = next((d for d, r in role_map.items() if r == "q1"), None)
        if q1_day:
            strides_day = next(
                (d for d, r in role_map.items()
                 if r.startswith("easy_") and _DAY_OFFSETS[d] == _DAY_OFFSETS[q1_day] - 1),
                None,
            )

    core: dict[str, Workout] = {}
    if "q1" in role_map.values():
        core["q1"] = (
            factory.time_trial(time_trial_km)
            if time_trial_km
            else _make_quality(factory, q1_type, q1_km, week_in_phase, deload, week_km)
        )
    if "q2" in role_map.values():
        core["q2"] = (
            factory.easy_run(q2_km)
            if demote_q2
            else _make_quality(factory, q2_type, q2_km, week_in_phase, deload, week_km)
        )
    num_easy = sum(1 for r in role_map.values() if r.startswith("easy_"))
    # The long run is the week's volume dial: quality sessions carry fixed
    # overhead that can overshoot their budget, so size the long run to the
    # actual remainder (leaving ~2km per easy day), within sane bounds.
    q_km = sum((w.estimated_distance_meters or 0) / 1000 for w in core.values())
    rem = week_km - q_km
    if num_easy:
        long_km = min(long_km, max(rem - 2.0 * num_easy, week_km * 0.30))
    else:
        long_km = max(rem, week_km * 0.33)
    long_km = round(min(long_km, week_km * 0.48), 1)
    core["long_run"] = _make_long_run(factory, lr_type, long_km, rehearsal=lr_rehearsal)
    core_km = sum((w.estimated_distance_meters or 0) / 1000 for w in core.values())
    if num_easy:
        remainder = week_km - core_km
        # A sub-2km jog isn't worth lacing up for — drop easy days rather than
        # padding them, so the week's total respects the volume curve.
        while num_easy and remainder / num_easy < 2.0:
            drop = next(
                d for d in reversed(sorted_days) if role_map.get(d, "").startswith("easy_")
            )
            del role_map[drop]
            num_easy -= 1
        per_easy_km = round(remainder / num_easy, 1) if num_easy else 0.0

    all_day_names = list(_DAY_OFFSETS.keys())
    training_set = set(days)
    workouts: list[Workout] = []

    for offset in range(7):
        day_name = all_day_names[offset]
        workout_date = week_start + timedelta(days=offset)

        if day_name not in training_set:
            continue  # non-training days are implicit rest — no placeholder entry

        role = role_map.get(day_name)
        if role is None:
            continue  # easy day dropped to respect the week's volume budget

        if role in core:
            w = core[role]
        elif (
            day_name == strides_day
            if strides_day
            else easy_type == "easy_with_strides"
        ):
            w = factory.easy_with_strides(per_easy_km)
        else:
            w = factory.easy_run(per_easy_km)

        w.scheduled_date = workout_date
        workouts.append(w)

    return workouts


def _make_quality(
    factory: WorkoutFactory,
    slot_type: str,
    budget_km: float,
    week_in_phase: int,
    deload: bool,
    week_km: float,
) -> Workout:
    """Build a quality session from its variant table (Canova-lever walk).

    Distance-driven slots (strides, progressive) size to their budget directly;
    everything else selects a variant by position in the phase, volume-gated.
    """
    if slot_type == "easy_with_strides":
        return factory.easy_with_strides(budget_km)
    if slot_type == "progressive":
        return factory.progressive_run(budget_km)
    method, kwargs, _ = pick_variant(slot_type, week_in_phase, deload, week_km)
    kwargs = dict(kwargs)
    if method == "fartlek":
        # ~4.5 min/km average — keep the session inside its distance budget.
        kwargs["total_min"] = max(20, min(kwargs["total_min"], round(budget_km * 4.5)))
    return getattr(factory, method)(**kwargs)


def _make_long_run(
    factory: WorkoutFactory, lr_type: str, distance_km: float, rehearsal: bool = False
) -> Workout:
    """Generate long run based on rotation type."""
    if lr_type == "long_progressive":
        return factory.long_run_progressive(distance_km)
    elif lr_type == "long_blocks":
        return factory.long_run_blocks(distance_km)
    elif lr_type == "long_with_race_pace":
        rp_km = min(8, distance_km * 0.4) if rehearsal else min(4, distance_km * 0.25)
        return factory.long_run_with_race_pace(distance_km, race_pace_km=rp_km)
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
        pace_key = None
        if paces and sd.get("pace") in ZONE_KEYS:
            target_type = IntensityTarget.PACE
            pace_key = sd["pace"]
            target_low, target_high = paces.band(pace_key)

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
                    pace_key=pace_key,
                )
            )

    return steps
