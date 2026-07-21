# Training-plan overhaul — 2026-07-21 (overnight, Victor asleep)

Victor's verdict on the old plans: "absolute garbage — not clear what I need to do
each day; no intervals/speeds/times; Garmin push is shit. Mimic Runna."

## What was actually wrong (4-agent investigation)

1. **The active plan predated the 2026-07-08 engine upgrade by 1.5 days** and was
   never regenerated: no pace bands, no per-step pace keys, `briefing=null` on all
   36 workouts, two hand-edited race-week days with empty step lists. The engine
   could already do far better; the plan just never used it.
2. **The portal threw away the structure that existed**: interval repeat blocks
   were rendered as one vague line — `repeat_count`, nested work/recovery steps,
   pace bands and `cadence_target` were all ignored by the renderer (it even read
   field names that don't exist in the schema).
3. **Garmin push was mostly sound** (real repeat groups, pace.zone ranges in m/s,
   dedup, scheduling) but never sent cadence, and it was pushing the impoverished
   old-format steps.
4. **Wording used coach jargon** ("3.0 min at I pace") instead of Runna's plain
   language.

## What changed (paceforge `b14fc41` + follow-ups)

- **Engine wording (Runna-style)**: warm-up = "N min easy jog at conversational
  pace"; short recoveries = "45s walking rest", long = "recovery jog"; work reps
  anchored to race efforts ("3 min hard — 3K-5K race effort", "400m fast &
  relaxed — mile race effort"). Cadence targets on VO2 (172), speed (174), hills
  (170) sessions.
- **Portal — new session-breakdown component** (used on Today inline, Plan modal,
  Calendar detail): every step is a row with kind (Warm up / Work / Recover /
  Cool down), what to do, distance-or-time, and its pace band; interval sets are
  boxed "N ×" blocks with the work/recovery children inside; totals + cadence
  footer. Week cards show the one-line session structure. Briefings (why /
  structure / feel / if-it-goes-wrong / cue) render in the detail views.
- **Garmin push**: cadence window (±5 spm) now emitted as the step target on
  effort-based (open) work steps — pace targets always win where they exist —
  plus a cadence line in every workout description.

## The new plan

Regenerated with the current engine + fresh Garmin data (VDOT 53.4):
**Half Marathon — 2026-09-20, target 1:25:00 (4:02/km), 12-week arc, Mon/Wed/Fri,
long runs Friday.** All 36 sessions carry structured step trees with real pace
bands, briefings, and athlete-specific coaching notes (AI enrichment pass, all
36/36). Past weeks 1–3 of the arc were retro-matched against actual completed
activities during the sync. Old Garmin copies of the previous plan's workouts
were deleted first; **weeks 4–12 pushed to the Garmin calendar** with structured
steps (pace ranges per step, repeat blocks, per-step watch notes).

## How it behaves on the watch (worth knowing — from the Runna research)

- Each step shows its own target pace range; step transitions buzz + lap.
- **Turn OFF Auto Lap and Auto Pause** for these workouts (Auto Lap splits laps
  mid-interval; Auto Pause kills recovery countdowns when you walk). Turn ON
  workout/pace audio alerts in Garmin Connect. This mirrors Runna's own setup
  guidance.
- VO2/speed/hill sessions carry cadence guidance (~170-174 spm) in the workout
  description; hill-type effort reps use a cadence window as the on-watch target.

## Ongoing behavior

- Daily 06:45 sync keeps completions matched; Monday autosync re-pushes the next
  2 weeks (dedup by stored Garmin ids); Monday coach review continues weekly.
- Regenerate any time from the portal (Plan → Create Plan) — everything in this
  report applies automatically.
