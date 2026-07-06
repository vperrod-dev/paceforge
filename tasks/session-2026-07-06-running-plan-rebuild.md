# PaceForge — Session handoff 2026-07-06

Running-plan AI rebuild + a long debugging saga to make it actually work end-to-end.
Everything merged to `master` (PRs #48–#61), 270 tests green, deployed live.

## What was built

**Goal:** running-only, event-driven plans, AI-driven for variety/experience, button-driven
from the portal, with visible build progress and Garmin-loadable workouts.

**Pipeline (final, working):**
`Create Plan` button → `plan.yml` (workflow_dispatch) →
1. deterministic engine scaffold (`paceforge plan --goal <event> …`, running-only, sets `accepted:true`) → **commits a safety-net plan** (never empty),
2. **AI coach enrichment** (`claude-code-action`, `--max-turns 200`, `continue-on-error`) — adds variety + personalized coaching notes from `profile.json`, commits on top,
→ `pages.yml` rebuilds (plan added to its `workflow_run` list) → portal shows it.

**Engine (Phase 1, deterministic depth):** `engine/events.py` (per-event structure),
volume anchored to athlete mileage, week-over-week progression, running-only (HYROX =
compromised 1km repeats, no station/strength), tightened `validate.py` (interval/rep
length caps, long-run cap, taper).

**Garmin:** `pace.zone` push fix (was `speed.zone` → km/h), `garmin_clear_calendar`
(via `/calendar-service`), `calendar_edit` (reschedule/delete + Garmin sync),
`garmin_delete`, and `_fallback_steps` so step-less workouts still load on the watch.

**Portal (`web/index.html`):** Create / Reassess / Delete-from-Garmin buttons, editable
calendar (reschedule/delete → `calendar-edit.yml`), **live build-progress banner** with
staged ticks (Designing structure → Saved draft → AI coach adding variety → Publishing),
GitHub-token hint, `Reset` cache-bust, plan renders on `weeks` (not `accepted`).

## Debugging saga — root causes fixed (so they don't recur)
- **claude-code-action hit ~28-turn limit → `is_error:true`, committed nothing, workflow still "success"** → every Create Plan silently produced no plan. Fix: deterministic safety-net commit first + `--max-turns 200` + `continue-on-error`.
- **`plan.yml` didn't trigger Pages** (GITHUB_TOKEN pushes don't fire `push`; plan wasn't in `pages.yml` `workflow_run`) → new plan never deployed. Fixed.
- **Portal only showed `accepted` plans**, generation never set it → plan invisible. Fix: render on `weeks`; set `accepted:true`.
- **`Reset` re-read the in-memory `loadJSON` cache** → never cleared a wiped/updated plan. Fix: bust `cache['f:plan.json']` + clear `pf_plan` localStorage.
- **Banner was gated inside the empty-state** → with a plan present it never showed. Fix: moved to top of `renderPlan`; instant on click via `planDispatchedAt` + jump to Plan tab.
- **Browser cache** was the recurring invisibility culprit — hard-refresh (Cmd/Ctrl+Shift+R) needed after each deploy.
- **Garmin calendar cleared:** 48 old workouts deleted, verified 0.
- **Garmin-friendliness:** verified via the real payload builder — 33/36 workouts already structured + paced; step-less race-week entries now get a fallback paced step.

## Current state
- All merged to `master`; live at https://vperrod.github.io/paceforge/ .
- AI enrichment **verified working**: a run produced 38 workouts each with personalized
  notes (e.g. read `training_readiness 44` / HRV and dialled a session back).
- Garmin calendar is empty (cleared this session).

## Open items / next session
- **USER TO TEST (only he can):** click **Push to Garmin**, open a workout on the watch,
  confirm it loads with per-step min/km pace. Local Garmin token is stale (Jun 29);
  interactive `paceforge login` (MFA) can't run via Claude's `!` shell — needs a real
  terminal. CI `GARMIN_TOKEN` secret is fresh (worked today).
- If a workout won't load/track, get the **specific device symptom** (which workout, what
  the watch shows) — structure was diagnosed blind.
- `bypassPermissions` is set **globally** in `~/.claude/settings.json` (line 5) — also
  disables guardrails on InvestmentPlatform (live trading). Consider scoping per-project.
- Nice-to-haves: race-day entry shouldn't push as an easy run (skip it); hills could carry
  HR targets; surface AI-enrichment failure in the banner (currently silent, safe fallback).

## Key files
- Workflows: `.github/workflows/{plan,pages,garmin-clear-calendar,calendar-edit,garmin-delete,push}.yml`
- Skill: `.claude/skills/running-plan/SKILL.md`
- Engine: `src/paceforge/engine/{events,planner,validate}.py`
- Garmin: `src/paceforge/garmin/client.py` (`_fallback_steps`, `pace.zone`, `get_scheduled_workouts` calendar-service)
- Actions: `src/paceforge/actions.py` (`garmin_delete`, `calendar_edit`, `garmin_clear_calendar`)
- Portal: `web/index.html` (buttons, banner, `planStageList`, `planStore.reset`)
- Spec/plan: `docs/superpowers/specs|plans/2026-07-06-running-plan-ai-rebuild*`
- Earlier deep review: `tasks/deep-review-2026-07-06.md`
