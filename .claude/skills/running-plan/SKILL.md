---
name: running-plan
description: Build or reassess the athlete's RUNNING training plan via a multi-role coaching panel. Use when the Create Plan / Reassess button fires (plan.yml), or the athlete says "build my running plan", "create a plan for my race", "reassess my plan". Running only — no strength/station sessions.
---

# Running-Plan Coaching Panel

Build a **running-only** plan through a genuine multi-role coaching panel. Depth and
quality matter more than speed — take the time to get it right. The `paceforge`
package owns the maths (VDOT→paces, periodised scaffold, validation); the panel owns
the **judgement**. State is files in `data/`. Run `paceforge` via the venv locally
(`.venv/bin/paceforge ...`); in CI it is on `PATH`.

## Inputs
From the workflow (env vars or the prompt): `mode` (create|reassess), `event_type`
(5K/10K/HALF_MARATHON/MARATHON/HYROX), `target_date`, `days`, `level`, optional
`goal_time`. Missing value → sensible default, and say so.

## The loop (create mode)
1. **Evidence.** Read `data/profile.json` and run `paceforge analyze` — aerobic /
   economy / load-recovery / race-prediction / limiters / readiness. For HYROX also
   read `data/hyrox_analysis.json`. This is the panel's evidence base.
2. **Scaffold with the given event — mandatory, sets the paces:**
   `paceforge plan --goal <EVENT_TYPE> --date <TARGET_DATE> --level <LEVEL> --days <DAYS>`
   (`--target-time <sec>` if given). Never invent paces; never change the event.
3. **Panel deliberation** — work the plan through these roles, then converge. Take as
   many rounds as the plan needs:
   - **Head Coach** — periodisation (base→build→peak→taper), 3:1 build:deload, total
     load; arbitrates; final call.
   - **Running Coach** — the sessions: paces (from the engine), variety (interval
     distances 200–2000m, tempo 20–35min, long-run styles), event-specific work. HYROX
     → threshold + compromised 1km repeats, goal-pace, even-pacing rehearsal.
   - **Strength & Conditioning Coach** — advisory only: injury/durability risk, running
     load vs the athlete's own S&C. May say "cut volume / swap a quality day for easy" —
     never adds a session.
   - **Athlete** — schedule realism + preferences + RPE/feel history from
     `profile.json`/`rpe.json`. Honour available days and recent load.
   - **Physio** — injury-history red flags.
   Protocol: Running Coach drafts → each role critiques → Head Coach synthesises →
   repeat until the panel agrees and it survives validation.
4. **Personalise** `data/plan.json` from the deliberation. The engine now owns
   variety, progression, structure and the per-session `briefing` (purpose /
   structure / feel / if_wrong / cue / venue / fuel / warmup) — do NOT rewrite
   sessions, reshuffle variants, or restate the briefing. Your layer is
   athlete-specific judgement: each workout's `notes` must ADD what the briefing
   cannot know — this athlete's readiness trend, RPE history ("your week-3 tempo
   felt 8/10, so this one holds pace"), the cadence flag, HYROX load on off-days,
   schedule realism. Tone rules: name the feel, give the why, pre-empt the failure
   mode. Also set week `focus` and plan `rationale`/`tips` from profile evidence,
   and adapt to readiness signals (swap a quality day to easy when flagged). Stay
   in the schema in `src/paceforge/models/plan.py`. Every workout stays a
   **running** type — never `hyrox_mixed`/`cross_training`. For HYROX the race is
   the plan's `target_date`, not a workout entry.
5. **Mark it active:** set `"accepted": true` in `data/plan.json` (so the portal shows
   it and Push works).
6. **Validate:** `paceforge validate` must return no issues. Fix what it flags; if a fix
   needs new paces, re-scaffold rather than invent.
7. **Human view:** run `paceforge plan-md` — the deterministic renderer builds
   `plan.md` from `data/plan.json` (briefings, week intros, pace bands included).
   Never hand-write plan.md.
8. **Commit** `data/plan.json` and `plan.md` and push.

## Reassess mode
Skip the scaffold. `paceforge adapt --dry-run` for the deterministic reflow/readiness
moves, apply if sensible, run the panel over the changes, keep `accepted: true`,
`paceforge validate`, regenerate `plan.md`, commit.

Leave Garmin push/delete to the buttons — this skill only writes the plan.
