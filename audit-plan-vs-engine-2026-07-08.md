# Audit: Existing PaceForge Plan vs 2026-07-08 New Engine Requirements

Repo: `/home/azureuser/projects/paceforge`
Task: t_4672361e
Date: 2026-07-30

## 1. Scope / method

Read only. Covered: `CLAUDE.md`, `plan.md`, `data/plan.json`, `data/profile.json`,
`tasks/plan-quality-upgrade-2026-07-08.md` (v2 spec), `src/paceforge/engine/{planner,variants,briefings,validate,vdot,compliance}.py`,
plus the shipped commit map in `tasks/session-2026-07-08-plan-quality-upgrade.md`.

The active live plan the user trains to is `plan.md` (human-readable), backed by
`data/plan.json`. `data/plan.json` on disk is a stub (`name: "Test Plan"`,
empty `pace_bands`, no populated weeks, `vdot: null`); `plan.md` is the real
current artifact.

## 2. Existing active plan parameters

| Parameter | Value |
|---|---|
| Goal | HALF_MARATHON |
| Race date | 2026-09-20 |
| Target time | 85:00 |
| Weeks | 12 |
| VDOT | 53.4 (Garmin VO2 Max) |
| Run frequency | 3 days/week |
| Fidelity | `plan.md` rich text + coaching notes; `plan.json` stub; weekly km ~16.3→31.4 |
| Phases | Base (wks 1-4), Build (5-8), Peak (9-10), Taper (11-12) |
| Workout types | Easy, Tempo, Progressive, Long variants, Time Trials, VO2max, Speed reps, Hills |
| Long-run cap | ~50% of week at 3 days (consistent with C8) |
| Readiness gate text | Present on TT/VO2 days; numbers from profile snapshot |
| Coaching notes | cadence, HR gate LT 163, HYROX interference, heat rule, RPE |
| Auto-sync | Daily 06:20 + 3×/day + Mon 06:00 UTC |
| Autosync behavior | Push upcoming 2 weeks, delete stale + orphans |
| Plan enrichment | Claude via `running-plan` skill adds notes, rationale, tips |

## 3. What the new engine code/spec requires

From `plan-quality-upgrade-2026-07-08.md` and current modules:

| Requirement | Status in code/spec |
|---|---|
| Percentage-derived pace bands (`TrainingPaces.band`) | Implemented in `vdot.py` (`_BAND_FRAC`, `band()`) |
| `pace_bands` on plan + `pace_key` on steps | Model fields present in `plan.py` |
| Variant library and Canova ordering | `variants.py` present; planner dispatches it in `_build_varied_week` |
| Long-run rotation + dress rehearsal + taper rules | `_long_run_type` and template rotation implemented |
| Time-trial deload rule (≤1/4-6w, strips Q2) | Implemented in planner |
| Briefings per session + week intros | `briefings.py` present |
| `paceforge plan-md` deterministic renderer | CLI present (`cli.py`, `actions.plan_md`) |
| Goal-pace feasibility gate | `validate._check_goal_feasibility` uses VDOT prediction |
| Volume anchor to actual weekly mileage + ACWR ramp | `_starting_and_peak_km`, `generate_plan` caps present |
| Skeleton density at ≤3 run days | `demote_q2` condition implemented in planner |
| Frequency-scaled long-run cap | `_long_run_cap` implemented; also used in `_build_varied_week` distance allocation |
| Session variety/consecutive-week rule | `validate._check_session_variety` present |
| Garmin surgical fixes + autosync on CI | Commit map says shipped; code contains runner support |
| Pace insights (`compliance.py` heat-adjusted, pace status window) | `pace_metrics`, `pace_status` implemented |

## 4. Gaps between active plan and new engine

### Gap 1 — Active plan is pre-new-engine text; generated plan state is stale
- `plan.md` is rich human-generated text, but `plan.md` itself says the plan
predates the 2026-07-08 engine upgrade (open item in handoff doc:
“regenerate the plan (portal Create Plan) — active plan predates the new engine”).
- `data/plan.json` is a placeholder stub, so the deterministic engine has no
authoritative current-plan state.
- **Impact**: any validation/recalibration/compliance run against current
`plan.json` produces no useful results.
- **Required update**: regenerate the accepted plan from current profile/goal
using the shipped engine, then `plan-md` so `plan.md` and `plan.json` agree.

### Gap 2 — `plan.json` lacks populated engine fields
- Current `data/plan.json` has empty/placeholder `pace_bands`, `vdot`,
`pace_source`, `easy/marathon/threshold/interval/repetition_pace`,
`pace_bands`, weeks/sessions.
- Required post-PR1/PR2/PR3: populated pace bands and scalar paces per zone,
scaled to VDOT (or custom overrides), with each step carrying `pace_key`.
- **Required update**: populate plan.json by regenerating the plan via `paceforge plan`.

### Gap 3 — `plan.md` should come from `paceforge plan-md`, not manual text
- The spec explicitly states plan.md must be deterministic and never hand-written.
- Current `plan.md` appears hand-authored from old engine style.
- **Required update**: run `paceforge plan-md` after regeneration to replace
`plan.md`.

### Gap 4 — `target_time_seconds` is missing in persisted plan
- `validate.goal-feasibility`, recalibration, and `pace_bands["race"]` rely on this field.
- Current `data/plan.json` has `null`.
- **Required update**: ensure persistence stores `target_time_seconds`
(e.g., 3060 for 85:00 HM).

### Gap 5 — `pace_key` usage in current stored plan not verifiable/usable
- Model supports `WorkoutStep.pace_key`, but since stored plan is a stub, no
regenerated steps can be recalibrated.
- **Required update**: regenerated plan must set `pace_key` per work step for
future PR9/PR10 usage.

### Gap 6 — “Watch render confirm / Phase 0 open item”
- The shipped spec requires Victor confirm on-watch min/km ranges, transition beeps,
repeat-group rendering, step notes, and settings (auto-lap OFF, auto-pause OFF,
audio ON) before treating Garmin enhancement as done.
- **Required update**: live watch validation by Victor; cannot be done from repo code alone.

### Gap 7 — CI autosync Monday 06:00 UTC + `push.yml` persistence fix
- Handoff says push/autosync fix committed; actual CI files were removed from this
checkout because GitHub Actions was removed (cloud runner only, per CLAUDE.md).
- **Required update**: ensure `paceforge autosync` is invoked from the runner timers
on schedule; confirm `plan.json` is committed back after pushes.

## 5. Required updates to align with the new engine

1. Regenerate the accepted plan from the live profile/goal:
   `python3 -m paceforge plan --goal HALF_MARATHON --date 2026-09-04 --level interactive` 
   (or via portal Create Plan on the on-VM deployment); then accept.

2. Re-render `plan.md` deterministically:
   `python3 -m paceforge plan-md`
   verify `plan.md` content matches rendered engine output.

3. Confirm persisted `plan.json` contains:
   - populated `vdot`, scalar paces, `pace_bands`
   - `target_time_seconds`
   - full weeks/sessions with `briefing`, `completion_metrics`
   - step `pace_key` values

4. Verify live runner timers include Monday autosync and commit-back behavior:
   `systemctl --user status paceforge-autosync paceforge-sync paceforge-coach`

5. Complete open Phase 0 watch validation on real Garmin device.
   Checklist:
   - 1-week push from runner
   - watch shows min/km range per step
   - step notes render at transitions
   - auto-lap OFF, auto-pause OFF, audio prompts ON

6. After enough completed quality sessions (≥5 over ≥3 weeks), verify pace-insights
chip/status appears in the portal (`compliance.pace_status`).

## 6. Risk notes / traps

-游乐场 “Test Plan” `plan.json` should not be accidentally accepted as the real plan; keep in audits only, then regenerate.
- If the profile `vo2_max` changes during audits, recalibration logic uses `accepted` flag; do not accept a regenerated plan without confirming with the athlete.
- `plan.md` is currently delivered via a public Caddy portal; any regeneration should also update the portal surface so displayed plan stays in sync.
