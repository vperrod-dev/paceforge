"""Coaching briefings — every session ships purpose / structure / feel /
failure-mode advice (plus execution cue, venue, fueling and warm-up notes
where they matter).

The engine fills these deterministically from the built workout; the
``running-plan`` panel skill layers athlete-specific judgement in
``Workout.notes`` on top — briefings say what the session is FOR, notes say
what it means for THIS athlete THIS week.
"""

from __future__ import annotations

from paceforge.models.plan import Workout, WorkoutStep, WorkoutType

# Sessions where the recovery/quality trade-off is coached explicitly.
_QUALITY_TYPES = {
    WorkoutType.TEMPO, WorkoutType.THRESHOLD, WorkoutType.RACE_PACE,
    WorkoutType.VO2MAX, WorkoutType.SPEED, WorkoutType.HILLS,
    WorkoutType.FARTLEK, WorkoutType.PROGRESSIVE, WorkoutType.INTERVALS,
}

# purpose / feel / if_wrong per workout type. {phase} is filled at build time.
_T: dict[WorkoutType, dict[str, str]] = {
    WorkoutType.EASY_RUN: {
        "purpose": "Aerobic base — most of your fitness is built here, at an effort "
        "that lets you absorb the hard days instead of digging the hole deeper.",
        "feel": "Conversational, RPE 3-4. You should finish feeling like you could do it again.",
        "if_wrong": "If pace drifts above the window to hold a conversation, let it — "
        "easy means effort, not a number. Heart rate above ~75% max: slow down.",
    },
    WorkoutType.RECOVERY: {
        "purpose": "Active recovery — blood flow without training stress.",
        "feel": "Genuinely gentle, RPE 2-3. Slower than feels natural.",
        "if_wrong": "Any temptation to push: remember this run's job is tomorrow's session.",
    },
    WorkoutType.EASY_WITH_STRIDES: {
        "purpose": "Easy volume plus neuromuscular priming — strides teach fast, relaxed "
        "turnover without fatigue, and set up the next quality day.",
        "feel": "Easy throughout; strides are fast and springy, ~90% effort, never sprinted.",
        "if_wrong": "Strides feeling forced or heavy-legged? Cut them — the easy running "
        "is the session; strides are a bonus.",
    },
    WorkoutType.LONG_RUN: {
        "purpose": "Endurance — time on feet grows capillaries, fat metabolism and "
        "durability. Unstructured on purpose: no targets, run to feel, switch off.",
        "feel": "Relaxed, conversational. The watch stays quiet today — that's the point.",
        "if_wrong": "Fading late is normal early in a plan; walk breaks beat abandoning. "
        "Feeling great ≠ speed up — save it for the structured long runs.",
    },
    WorkoutType.LONG_RUN_PROGRESSIVE: {
        "purpose": "Endurance plus fatigue-resistance — running strong in the back half "
        "is exactly the race-day skill, trained under control.",
        "feel": "Patient early, purposeful late. The final segment is honest work, RPE 6-7.",
        "if_wrong": "If the faster segments break form, back off to the slow edge of the "
        "window — finishing strong matters more than the split.",
    },
    WorkoutType.LONG_RUN_WITH_RACE_PACE: {
        "purpose": "Race specificity — goal pace on tired legs, plus a dress rehearsal "
        "for pacing, fueling and kit.",
        "feel": "Race-pace block should feel controlled and rhythmic, not desperate — "
        "lock in after 1km and relax into it.",
        "if_wrong": "Can't hold the window without straining? Shorten the block rather "
        "than slowing the whole run — quality of pace beats quantity today.",
    },
    WorkoutType.TEMPO: {
        "purpose": [
            "Lactate threshold — raises the pace you can sustain. The single "
            "biggest lever for {phase}-phase fitness at your distance.",
            "Sustained comfortably-hard running moves the pace you can hold for an "
            "hour — the most trainable lever there is for race performance.",
        ],
        "feel": "Comfortably hard, RPE 7. You could speak a sentence, not hold a chat.",
        "if_wrong": "Too hard? Slow 5-10 s/km rather than stopping — the aerobic stimulus "
        "survives a slower tempo, not a broken one. Heat or hills: switch to effort.",
    },
    WorkoutType.THRESHOLD: {
        "purpose": [
            "Lactate threshold in pieces — same stimulus as tempo with the mental "
            "load broken up. Floats/recoveries keep the lactate shuttling.",
            "Cruise work at the red-line edge: enough stimulus to move your "
            "threshold, broken up so form never collapses.",
        ],
        "feel": "Comfortably hard, RPE 7-8. The last rep should feel like one more was possible.",
        "if_wrong": "Fading mid-set: slow 5 s/km, don't bail. If floats become jogs, "
        "you started too fast — that's the lesson, bank it.",
    },
    WorkoutType.VO2MAX: {
        "purpose": [
            "Aerobic ceiling — short hard reps at ~3K-5K effort push maximal "
            "oxygen uptake, which everything below it hangs from.",
            "Aerobic power day — hard reps flood the engine with oxygen demand "
            "and lift the ceiling every other pace hangs from.",
        ],
        "feel": "Hard, RPE 8-9. Controlled discomfort — the last rep matches the first.",
        "if_wrong": "Fading before the final rep: slow 5 s/km or take 30s more recovery. "
        "In heat or wind run by RPE 8 — the pace window assumes calm, flat ground.",
    },
    WorkoutType.SPEED: {
        "purpose": "Speed and running economy — short, fast reps recruit fast-twitch "
        "fibres and sharpen form, making every slower pace cheaper.",
        "feel": "Fast, springy and light — ~95%, never an all-out sprint. Full recovery "
        "is part of the design; R work only counts when you're fresh for each rep.",
        "if_wrong": "Form breaking (shoulders up, overstriding)? Stop the set — junk reps "
        "train junk form. These reps are about quality, never volume.",
    },
    WorkoutType.HILLS: {
        "purpose": "Strength, power and economy — uphill running loads the posterior "
        "chain at low impact and forces a strong knee drive.",
        "feel": "Hard but controlled, RPE 8 — effort-based, forget pace on a gradient.",
        "if_wrong": "Calves or achilles complaining? Shorten the reps and stay tall — "
        "lean from the ankles, not the waist.",
    },
    WorkoutType.FARTLEK: {
        "purpose": "Speed play — unstructured surges build gear changes and make hard "
        "running feel playful again. Deliberately loose.",
        "feel": "Surges roughly threshold-to-5K effort, by feel. Have fun with it.",
        "if_wrong": "If every surge becomes a time trial, you've missed the point — vary "
        "them, land some easy ones.",
    },
    WorkoutType.PROGRESSIVE: {
        "purpose": "Pacing discipline — each third faster teaches negative splitting, "
        "the highest-percentage race strategy there is.",
        "feel": "First third annoyingly easy, last third honest work. Smooth gear changes.",
        "if_wrong": "If the final third isn't the fastest, the start was too quick — "
        "that's the exact race-day error this session exists to fix.",
    },
    WorkoutType.RACE_PACE: {
        "purpose": "Race specificity — goal pace becomes automatic through repetition. "
        "Rhythm, relaxation and confidence at the pace that matters.",
        "feel": "Should feel 'sustainably quick' — if it feels like a fight now, the "
        "goal needs re-examining (that's useful information, not failure).",
        "if_wrong": "Consistently outside the window at honest effort: log it — the "
        "adaptive review uses exactly this signal to adjust your paces.",
    },
}

_CUES: dict[WorkoutType, str] = {
    WorkoutType.EASY_RUN: "Cadence: count 30 right-foot strikes in 20s (target creeping "
    "up over the plan) — quicker, shorter steps, no overstriding.",
    WorkoutType.EASY_WITH_STRIDES: "Strides are turnover practice: quick light steps, "
    "arms driving straight back, eyes up.",
    WorkoutType.LONG_RUN: "Check posture every ~15min: tall hips, relaxed shoulders, "
    "quiet feet.",
    WorkoutType.HILLS: "Drive the knee, push the ground away, arms compact — and walk "
    "the first 20m of each descent before jogging.",
    WorkoutType.SPEED: "Think 'fast feet on hot coals' — ground contact short, heels "
    "never settling.",
    WorkoutType.VO2MAX: "Relax the face and hands on the back half of each rep — "
    "tension is free speed lost.",
    WorkoutType.TEMPO: "Lock the rhythm with your breathing (e.g. 2:2) and let pace "
    "follow it.",
    WorkoutType.PROGRESSIVE: "Change gear with cadence first, stride length second.",
}

_VENUES: dict[WorkoutType, str] = {
    WorkoutType.HILLS: "Find a steady 4-6% gradient that takes 45-75s to climb; "
    "grass or trail saves the calves.",
    WorkoutType.SPEED: "Track or a measured flat stretch — GPS pace lies over 200-400m, "
    "so run these by effort and check splits after.",
}


def _fmt(sec_per_km: float) -> str:
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}"


def _step_text(step: WorkoutStep) -> str:
    txt = step.description or step.step_type.value
    if step.target_low and step.target_high and step.target_low != step.target_high:
        txt += f" @ {_fmt(step.target_low)}-{_fmt(step.target_high)}/km"
    return txt


def build_structure(workout: Workout) -> str:
    """Human-readable step breakdown with pace windows, derived from the steps."""
    parts: list[str] = []
    for step in workout.steps:
        if step.repeat_count and step.steps:
            inner = " / ".join(_step_text(s) for s in step.steps)
            parts.append(f"{step.repeat_count}× ({inner})")
        else:
            parts.append(_step_text(step))
    return " → ".join(parts)


def _pick(v: str | list[str], rot: int) -> str:
    return v if isinstance(v, str) else v[rot % len(v)]


# One-line phase context appended to quality purposes — the athlete should
# always know WHY this session sits in THIS part of the plan.
_PHASE_TAIL = {
    "Base": " Right now this is groundwork — economy and resilience for the harder blocks ahead.",
    "Build": " This is the meat of the build: each week stacks a little more than the last.",
    "Peak": " Race-sharpening territory — quality stays, fatigue drains away.",
    "Taper": " Small dose on purpose: keep the legs awake while the taper does its work.",
}


def build_briefing(
    workout: Workout,
    phase: str = "",
    hyrox: bool = False,
    rot: int = 0,
) -> dict[str, str]:
    """Assemble the coaching briefing for a built workout. ``rot`` selects
    among text alternates deterministically (planner passes wk_idx + seed)."""
    structure = build_structure(workout) or workout.description or workout.name
    if "RACE DAY" in workout.name.upper():
        return {
            "purpose": "The day it was all for. Nothing new today — the kit, fueling "
            "and pacing you rehearsed are the plan.",
            "structure": structure,
            "feel": "First third controlled (it should feel too easy), middle third "
            "rhythmic, final third everything you have left.",
            "if_wrong": "Bad patch mid-race? They pass — ease 5 s/km for 2 minutes, "
            "take fuel, rebuild. Never surge to 'make up' time.",
            "fuel": "Race-day intake exactly as rehearsed on the long runs.",
        }
    t = _T.get(workout.workout_type)
    if t is None:
        return {"purpose": workout.description or workout.name, "structure": structure}
    purpose = _pick(t["purpose"], rot).format(phase=phase or "this")
    if workout.workout_type in _QUALITY_TYPES and phase in _PHASE_TAIL:
        purpose += _PHASE_TAIL[phase]
    b: dict[str, str] = {
        "purpose": purpose,
        "structure": structure,
        "feel": _pick(t["feel"], rot),
        "if_wrong": _pick(t["if_wrong"], rot),
    }
    if "Time Trial" in workout.name:
        b["purpose"] = (
            "Benchmark — an honest maximal effort measures fitness better than any "
            "formula, recalibrates your training paces, and doubles as race practice."
        )
        b["if_wrong"] = (
            "Conditions bad (heat, wind, illness)? Postpone rather than run a false "
            "benchmark — a wrong number miscalibrates every pace that follows."
        )
        b["venue"] = "Flat, repeatable course (or parkrun/track) — same venue each time."
        b["warmup"] = (
            "Treat the warm-up like race day: 15min easy + drills + 3 strides, "
            "then 2min standing rest before the start."
        )
    if workout.workout_type in (WorkoutType.SPEED, WorkoutType.VO2MAX):
        b["warmup"] = (
            "After the easy warm-up: 2-3 drills (high knees, A-skips) plus 2-3 strides "
            "— fast reps on a cold engine is how calves tear."
        )
    cue = _CUES.get(workout.workout_type)
    if cue:
        b["cue"] = cue
    venue = _VENUES.get(workout.workout_type)
    if venue:
        b.setdefault("venue", venue)
    dur_min = (workout.estimated_duration_seconds or 0) / 60
    if dur_min >= 75 or workout.workout_type == WorkoutType.LONG_RUN_WITH_RACE_PACE:
        b["fuel"] = (
            "Fuel it: carbs beforehand, then practice race-day intake — a gel every "
            "~25-30min and sips of fluid. The gut is trainable; race day is not the "
            "day to find out."
        )
    if hyrox and workout.workout_type in _QUALITY_TYPES:
        b["if_wrong"] += (
            " Legs dead from yesterday's stations? Run it at the slow edge of the "
            "window or swap with the easy day — interference is real, fighting it isn't "
            "training."
        )
    return b


def week_intro(
    phase: str, week_in_phase: int, phase_len: int, deload: bool, weeks_to_race: int
) -> str:
    """One paragraph on this week's role in the plan arc."""
    if weeks_to_race == 0:
        return (
            "Race week. The work is banked — nothing you do now makes you fitter, "
            "plenty can make you tired. Short, sharp, rested."
        )
    if deload:
        return (
            f"Cutback week ({phase} phase) — volume drops on purpose. Adaptation "
            "happens in the recovery, not the work; resist making up the kilometres, "
            "next week builds from a higher base because of this one."
        )
    pos = f"week {week_in_phase + 1} of {phase_len}"
    arc = {
        "Base": "laying aerobic foundation and durable form — economy work now makes "
        "every later phase cheaper",
        "Build": "the engine room — threshold and VO2 work stack week over week, each "
        "session one visible step up on the last",
        "Peak": "converting fitness to race-readiness — race-pace work dominates and "
        "sessions look like the race",
        "Taper": "shedding fatigue while keeping the engine ticking over — volume "
        "falls, intensity stays",
    }.get(phase, "progressing the plan")
    out = f"{phase} {pos}: {arc}."
    if 0 < weeks_to_race <= 4:
        out += f" {weeks_to_race} weeks to race day."
    return out
