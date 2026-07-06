---
name: running-plan
description: Build or reassess the athlete's RUNNING training plan. Use when the Create Plan / Reassess button fires (plan.yml), or the athlete says "build my running plan", "create a plan for my race", "reassess my plan". Running only — no strength/station sessions.
---

# Running-Plan Coach

Build a **running-only** plan for the athlete's event, fast. The `paceforge`
package owns the maths (VDOT→paces, periodised scaffold, validation); you own the
**judgement** — personalise the scaffold in ONE pass. Keep it tight: no multi-round
debates, no re-syncing Garmin. State is files in `data/`. Run `paceforge` via the
venv locally (`.venv/bin/paceforge ...`); in CI it is on `PATH`.

## Inputs
Given by the workflow (env vars or the prompt): `mode` (create|reassess),
`event_type` (5K/10K/HALF_MARATHON/MARATHON/HYROX), `target_date`, `days`, `level`,
optional `goal_time`. If a value is missing, use a sensible default and say so.

## Do this (create mode)
1. **Scaffold with the given event — mandatory, sets the paces:**
   `paceforge plan --goal <EVENT_TYPE> --date <TARGET_DATE> --level <LEVEL> --days <DAYS>`
   (add `--target-time <sec>` if a goal time was given). Writes a valid, running-only
   `data/plan.json`. Never invent paces; never change the event.
2. **Personalise in one pass** — edit `data/plan.json`: tune week `focus` and each
   workout's `notes` (purpose + feel, specific not generic), add variety where two
   sessions are identical, adapt to obvious signals in `data/profile.json` (low
   `training_readiness`/`hrv_status: Low` → swap a quality day for easy). Stay in the
   schema in `src/paceforge/models/plan.py`. Every workout stays a **running** type —
   never `hyrox_mixed`/`cross_training`. For HYROX bias to threshold + compromised 1km
   repeats; the race is the plan's `target_date`, not a workout.
3. **Mark it active:** set `"accepted": true` in `data/plan.json` (so the portal shows
   it and Push works).
4. **Validate:** `paceforge validate` must return no issues. Fix what it flags; if a
   fix needs new paces, re-scaffold rather than invent.
5. **Human view:** regenerate `plan.md` from `data/plan.json`.
6. **Commit** `data/plan.json` and `plan.md` and push.

## Reassess mode
Skip the scaffold. Run `paceforge adapt --dry-run` for the deterministic reflow/
readiness moves, apply if sensible, personalise lightly, keep `accepted: true`,
`paceforge validate`, regenerate `plan.md`, commit.

## Coaching lens (apply in the single pass, don't role-play separately)
Head-coach periodisation (base→build→peak→taper, 3:1 build:deload), running-coach
variety (interval distances 200–2000m, tempo 20–35min, long-run styles), S&C caution
(don't stack hard days; cut volume if readiness low), athlete realism (respect the
given days). Leave Garmin push/delete to the buttons — this skill only writes the plan.
