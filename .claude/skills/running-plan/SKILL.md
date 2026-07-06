---
name: running-plan
description: Build or reassess the athlete's RUNNING training plan via a multi-role coaching panel. Use when the Create Plan or Reassess button fires (the plan.yml workflow), or the athlete says "build my running plan", "create a plan for my race", "reassess my plan". Running only — no strength/station sessions in the plan.
---

# Running-Plan Coaching Panel

You generate the athlete's **running-only** training plan by running a short
multi-role panel over the deterministic scaffold. The `paceforge` package owns the
maths (VDOT→paces, periodised scaffold, validation); you own the **judgement** —
session selection, variety, progression, event-specific structure, and coaching
notes. The plan is **running only**: never add strength, station, brick, or
cross-training sessions. Strength is represented only by the S&C reviewer's advice
(e.g. "cut volume, legs are cooked"), never as a workout entry.

State is files in `data/`; you read and write them, then stop. Run `paceforge`
through the venv locally (`.venv/bin/paceforge ...`); in CI it is on `PATH`.

## Inputs (from the workflow or the athlete)
- `mode`: `create` (from params) or `reassess` (adapt the existing plan).
- Create params: event type (`5K`/`10K`/`HALF_MARATHON`/`MARATHON`/`HYROX`),
  target date, training days, optional goal time.

## The loop

1. **State.** `paceforge sync` if `data/sync-status.json` is stale (else skip).
2. **Evidence.** Read `data/profile.json` and run `paceforge analyze` — aerobic /
   economy / load-recovery / race-prediction / limiters / readiness. This is the
   panel's evidence base. For HYROX also read `data/hyrox_analysis.json`.
3. **Scaffold (create mode).** `paceforge plan --goal <EVENT> --date <YYYY-MM-DD>
   --level <level> --days tue,thu,sat,sun` writes a valid, running-only
   `data/plan.json` with **correct paces**. Start here — never invent paces.
   (Reassess mode: skip; run `paceforge adapt --dry-run` for the deterministic
   reflow/readiness moves, then refine.)
4. **Panel.** Deliberate the plan through these roles, then converge:
   - **Head Coach** — owns periodisation (base→build→peak→taper), total load, the
     3:1 build:deload rhythm, and the final call. Arbitrates disagreements.
   - **Running Coach** — drafts the sessions: paces (from the engine), variety (vary
     interval distances 200–2000m, tempo 20–35min, long-run styles), and
     event-specific work. For HYROX: bias to threshold + **compromised 1km
     repeats** (run-under-fatigue), goal-pace work, even-pacing rehearsal.
   - **Strength & Conditioning Coach** — advisory only. Flags injury/durability risk
     and running load vs the athlete's own separate S&C. May say "reduce volume" or
     "swap a quality day for easy" — never adds a session to the plan.
   - **Athlete** — schedule realism + preferences + RPE/feel history from
     `profile.json` / `rpe.json`. Honour available days, recent load, disliked
     session types.
   - **(optional) Physio** — injury-history red flags.
   Protocol: Running Coach drafts → the other roles critique in one pass → Head
   Coach synthesises the revisions. Keep it to 1–2 rounds; don't over-deliberate.
5. **Personalise** `data/plan.json` on top of the scaffold: tune week `focus`,
   workout `notes` (purpose + feel, specific not generic), variety, and adapt to
   current signals (low `training_readiness`/`hrv_status: Low` → swap a quality day
   for easy; strong trend → progress). Stay within the schema in
   `src/paceforge/models/plan.py`. Keep every workout a **running** type.
6. **Validate.** `paceforge validate` must return no issues before you finish. Fix
   whatever it flags — paces ordered, no back-to-back hard days, ramp ≤15%, interval
   reps ≤5min / speed ≤2min, long run ≤37% of week, final week tapers. If a fix
   needs new paces, don't invent them — re-scaffold.
7. **Human view.** Regenerate `plan.md` from `data/plan.json` — a scannable
   week-by-week markdown table that renders on github.com.

Leave Garmin push/delete to the explicit buttons (`push.yml` / `garmin-delete.yml`)
and calendar moves to `calendar-edit.yml` — this skill only writes the plan.

## Running-only guardrails
- Every `Workout.workout_type` must be a running type (easy_run, long_run, tempo,
  threshold, intervals, race_pace, vo2max, hills, fartlek, speed, recovery_run,
  progressive, strides). Never `hyrox_mixed` or `cross_training`.
- For HYROX, the race is the plan's `target_date`; do not add a race-day hybrid
  workout entry.
