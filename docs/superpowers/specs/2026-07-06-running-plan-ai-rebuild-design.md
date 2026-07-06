# Running-Plan AI Rebuild — Design Spec

**Date:** 2026-07-06
**Status:** Approved (Victor), ready for implementation plan.
**Companion findings:** `tasks/deep-review-2026-07-06.md`

## Problem

The plan generator produces simple, repetitive plans. Root cause (audited): it is a
fixed YAML template with `week % 4` type rotation and **hardcoded** workout parameters
(every VO2max week = 5×3.5 min, byte-identical week 4 vs 8), no progression, no real
periodization, and it ignores the athlete's readiness / limiter / goal data. The
`coach` skill (Claude, the intended judgement layer) exists but never runs from the
portal, so the athlete sees the raw scaffold.

## Goals

1. Plans are **running only**, shaped by the **event type** being prepared for
   (5K / 10K / half / marathon / HYROX). No strength/station sessions in the plan.
2. Plans are generated and reassessed by **Claude on the user's subscription** (no
   paid API), via a **multi-role coaching panel** encoded as a reusable skill.
3. Everything is **button-driven from the portal**. No cron, no scheduled checks.
4. Garmin: **push** and **delete** the plan via buttons; **reschedule/delete a single
   session** on the portal calendar auto-syncs to the Garmin calendar.

## Non-goals

- No strength/S&C session programming in the plan (the S&C coach is an advisory
  *reviewer* only).
- No scheduled/autonomous generation. No self-hosted runner. No LLM API usage.
- No live backend/server — the portal stays a static GitHub Pages SPA; all mutations
  go through GitHub `workflow_dispatch` → runner → commit → Pages rebuild.

## Key existing infrastructure (reused, already works)

- `coach.yml` / `analyze.yml` already run Claude via `anthropics/claude-code-action@v1`
  with `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` — **subscription
  auth, no API bill.** This is the proven spine.
- The portal already dispatches workflows from the browser via the GitHub REST API
  (`fetch(.../actions/workflows/<name>.yml/dispatches)`); Sync, Push, RPE, Ask-Coach
  all use it. New buttons extend this exact pattern.
- `push.yml` already pushes a plan week to Garmin as structured, scheduled workouts.
- `models/plan.py` already has per-`Workout` `garmin_workout_id` (delete-by-id) and
  `scheduled_date` — enough for per-session delete/reschedule sync.

## Architecture

Three layers, existing division of labour made real:

1. **Deterministic engine (facts + guardrails, never hallucinated)** — `engine/`:
   VDOT → exact pace bands; a **running-only, event-driven scaffold** with real
   periodization + week-to-week progression as the panel's canvas; the `WorkoutFactory`
   that renders session specs into correctly-paced, Garmin-ready steps; and a tightened
   `validate.py` hard gate.
2. **Judgement (Claude, subscription) — the `running-plan` skill** — a multi-role panel
   that drafts, critiques, and converges on the plan on top of the scaffold, then must
   pass `validate`.
3. **Portal + workflows (triggers + Garmin I/O)** — buttons dispatch workflows; Claude
   runs generation, deterministic Python runs Garmin push/delete/reschedule; results
   commit to `data/*.json` and Pages rebuilds.

### Data flow (all mutations)

```
browser button ─► GitHub API workflow_dispatch ─► workflow on GitHub runner
   ├─ generation → claude-code-action (subscription) runs running-plan skill
   └─ Garmin I/O → deterministic paceforge CLI (push / delete / reschedule)
         ─► commit data/*.json ─► Pages rebuild ─► portal reflects (minutes)
```

## Component 1 — Running-only, event-driven engine

- **Scope change:** plan generation emits running sessions only. Remove
  station-day/strength scheduling from `planner.py` (the `station_day` swap, HYROX
  `week_template`). HYROX event type still supported, but as a **running** plan:
  bias toward threshold, compromised 1 km repeats, and goal-pace work.
- **Event types** drive structure & pace anchors: `FIVE_K`, `TEN_K`, `HALF`, `MARATHON`,
  `HYROX`. Each maps to a phase arc, quality-session emphasis, long-run cap, and (HYROX)
  a compromised-running bias with run targets ≈ fresh pace + 25–40 s/km.
- **Scaffold strengthened** (the canvas): base→build→peak→taper tied to race date;
  3:1 build:deload; week-to-week progression via Canova's 3 levers (more/longer reps or
  shorter recovery at fixed pace) so no two weeks are identical; volume anchored to the
  athlete's actual `weekly_mileage_km` + recent activities, not a fixed table.
- **`validate.py` tightened** to coach-grade rules (the gate the panel must pass):
  per-zone weekly volume caps (T ≤10%, I ≤8%, R ≤5%), interval-rep length caps
  (I ≤5 min, R ≤2 min), long-run ≤25–30% of week, no back-to-back hard days, taper
  shape (volume −40–60%, intensity held), ramp/ACWR sanity (~0.8–1.3). Keep the existing
  pace-ordering and step-pace checks.
- **Honesty:** delete the false "AI-powered" docstring in `planner.py`; document
  scaffold = canvas, `running-plan` skill = generative judgement.
- **Data model:** running-only means the plan schema is a subset of today's; keep
  `WorkoutType` values but stop emitting HYROX_MIXED/CROSS_TRAINING from the planner.
  No breaking field changes anticipated; if the scaffold's shape changes enough to make
  the stored `plan.json` invalid, that's fine — see Rollout step 0 (wipe + regenerate).

## Component 2 — `running-plan` skill (multi-role panel)

New skill at `.claude/skills/running-plan/`. Invoked by the Create/Reassess workflows.
Roles and protocol:

- **Head Coach** — owns periodization/phase arc/total load; arbitrates; final call.
- **Running Coach** — drafts sessions: paces (from engine, never invented), variety,
  event-specific structure.
- **Strength & Conditioning Coach** — advisory only: injury/durability risk, running
  load vs the athlete's separate S&C, recovery. Never adds sessions to the plan.
- **Athlete** — schedule realism + preferences + RPE/feel history from `profile.json` /
  `rpe.json` (respect available days, avoid disliked session types, honour recent load).
- *(optional Physio — injury-history red flags.)*

Protocol: Running Coach drafts on the scaffold → panel critiques (parallel) → Head Coach
synthesizes revisions → `paceforge validate` → loop until it passes and the panel agrees
→ write `plan.json`, regenerate `plan.md`. Runs in `claude-code-action` on the
subscription token. Higher token cost per run than a single voice — acceptable because
it is on-demand, not scheduled. The lighter `coach` skill remains for "Ask Coach" issues.

**Reassess mode:** the same panel, seeded with recent activities + adherence + readiness,
adapts the existing plan (reflow/downgrade/progress) rather than generating from scratch.

## Component 3 — Portal buttons + workflows

- **Create Plan** — a params form (event type, race/target date, training days/week,
  goal time; prefilled from the athlete's target event where available) →
  new `plan.yml` (`workflow_dispatch` inputs) → `running-plan` skill (generate) → commit.
- **Reassess Plan** — `plan.yml` with `mode=reassess` → `running-plan` skill (adapt).
- **Push to Garmin** — existing `push.yml` (unchanged).
- **Delete from Garmin** — new `garmin-delete.yml` → CLI deletes every workout carrying a
  `garmin_workout_id` (`DELETE /workout-service/workout/{id}`), clears the ids, commits.
- All buttons reuse the existing browser→REST `workflow_dispatch` helper and busy/toast UX.

## Component 4 — Editable calendar → Garmin sync

- Portal calendar becomes editable: drag-to-reschedule and delete-session controls.
- Each edit dispatches `calendar-edit.yml` with inputs `{session_id, action, new_date}`.
- The workflow runs a new `paceforge calendar-edit` action that:
  - **reschedule:** move the workout's `scheduled_date`; on Garmin, delete the old
    `garmin_workout_id` and push the workout on the new date (store the new id);
  - **delete:** remove the workout from `plan.json`; delete its `garmin_workout_id` on
    Garmin;
  - then `validate`, regenerate `plan.md`, commit.
- Sync is automatic (no confirm), per requirement. Latency = same minutes-scale model as
  the Sync button; the portal shows an optimistic pending state until Pages rebuilds.

## Rollout

- **Step 0 (authorized):** once the new model + skill are ready, delete the current
  `data/plan.json` and clean all PaceForge workouts off the Garmin calendar (via the new
  delete action). Victor then clicks Create Plan to generate fresh under the new model.
- Ship engine + validate + delete/reschedule (TDD'd Python) first; then the skill; then
  the portal buttons + editable calendar; then Step 0 + first real Create Plan.

## Testing

- **Deterministic (TDD):** running-only scaffold (event-type structure, progression,
  no station/strength emitted), tightened `validate` rules, Garmin delete action,
  `calendar-edit` reschedule/delete + Garmin sync. Extend existing `tests/`.
- **Generation path:** one live `plan.yml` dispatch → assert the produced `plan.json`
  is running-only, varied (no two weeks identical), passes `validate`, and renders on
  the calendar. Verified by Victor from the portal (his vantage).
- **Garmin pacing** (already fixed this session): confirm on-watch after a push.

## Risks / open items (resolved during build, not blockers)

- Whether a Create-Plan params form already exists in the portal to extend vs build.
- Exact garminconnect delete/reschedule surface in the pinned fork.
- Browser-held GitHub token exposure is a pre-existing pattern (out of scope here; note
  for a later security pass — see the KinkLink leaked-PAT lesson).
