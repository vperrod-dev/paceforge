# Plan Quality Upgrade — Runna-Level Running Plans (v2, 2026-07-08)

v1 = research synthesis (repo map + Runna/Garmin/TrainingPeaks/NRC primary-source research).
v2 = v1 hardened by a three-way review round: **coach-science critique**, **engineering
fit against the actual code**, **Garmin payload feasibility verification**. v2 supersedes
v1 throughout; v1's research summary is kept below for context.

Victor's three complaints, verified:

| # | Complaint | Root cause (verified) | Verdict |
|---|-----------|----------------------|---------|
| 1 | Plans boring — same run every week, no varied paces/times | Session types picked from static length-4 pools `pool[week % 4]` (`planner.py:82-108,370-373`); workout params hardcoded (`planner.py:445-495`); only progression is a `_bump()` rep nudge; non-easy targets a fake ±3 s/km band (`workouts.py:96`). | Engine upgrade |
| 2 | Descriptions thin | `Workout.description` = 1–2 hardcoded sentences per generator, identical every week (`workouts.py`); no purpose/structure/feel/failure-mode standard; 1 canned focus line per week. | Content system |
| 3 | Not Garmin-enhanced | `pace.zone` id-6 fix live but unconfirmed on watch; REST/ACTIVE fall through to `interval`; zero-width widen is generic ±3 not the real easy band; HR steps silently `no.target`; no per-step notes; push manual per-week. | Surgical + confirm |

---

## Round-2 findings that change the plan (load-bearing)

**Coach-science (structural — v1 optimized decoration on an unsound week):**

- **C1. Skeleton density.** Sample plan runs 3 quality days out of 3 (week 6: 400s + cruise
  + progressive long = zero easy running). Rule: at ≤3 run days/wk, **max 2 quality
  sessions counting any hard long-run subtype** — a hard long run consumes a quality slot.
  Week = (Q1 + easy + hard long) or (Q1 + Q2 + easy long), never Q1+Q2+hard long.
  At 5+ days the current 2Q+long+2E skeleton is fine.
- **C2. Goal-pace feasibility gate.** Current plan: 85:00 HM = 4:02/km but T pace = 4:04 —
  every "race pace" block is supra-threshold mislabeled as marathon-pace work. Fix: derive
  race pace from `target_time_seconds`; validate flags goal pace < T pace; copy names the
  correct zone.
- **C3. Volume anchor / ACWR.** Athlete at ~15 km/wk; plan opens at 26 km + 3 quality =
  ACWR ≈ 1.75 (injury zone), worse with HYROX on off days. Week 1 must anchor to actual
  `weekly_mileage_km` (ramp ≤ ~1.3 acute:chronic); `validate.py` rule.
- **C4. Variant volume-gating.** Daniels caps (I ≤8%, R ≤5% of weekly km) must gate variant
  selection: each variant carries a min-weekly-km requirement; per-session I ~10–12 min,
  R ~2.5–3 km at this volume. 16×400 is a miler's session — out for HM.
- **C5. Phase→session ordering inverted.** For long events: **base** = hills/strides/
  fartlek/short T (economy); **build** = I + cruise T; **peak** = T volume + race-pace
  blocks; **taper** = short T + race-pace touches. R volume declines toward race day —
  current engine peaks 16×400 in week 10, backwards.
- **C6. Missing HM-specific variants:** threshold **alternations/floats** (5×(1km T / 1km M
  float) — the most race-specific HM session short of a rehearsal) and a continuous
  **M-pace steady run**. Kenyan hills / doubles correctly absent at 3 d/wk.
- **C7. Pace windows in v1 were 2–3× too narrow** (T ±4s etc. sits inside GPS noise).
  Percentage-based ~±3–4% of pace, asymmetric slow-side bias for I/R. At VDOT 54.7:
  M ±8 s/km, T −4/+10, I ±10, R ±8 (or R by effort, pace display only). Easy = the full
  table E range (already ~28 s wide).
- **C8. Long-run cap frequency-scaled.** ≤30% of week at 5+ days, **≤50% at 3 days** — the
  37% cap gave a 12 km max long run for an 85:00 half; needs ~90–110% of race duration
  (14–16 km) by peak.
- **C9. Benchmark repeats are a feature.** Variety rule scoped to **consecutive weeks**;
  tagged `benchmark` sessions may repeat ≥3 weeks apart (progress measurement, feeds
  Phase 4). Canova levers reset partially after each deload; recovery-shortening lever
  applies to T/I only, never R (R needs full recovery).
- **C10. Long-run rotation constraints:** last race-pace long run = dress rehearsal 2–3
  weeks out; taper long runs easy/unstructured only; unstructured mandatory the week
  after the biggest race-pace long run and in every cutback week.
- **C11. Time trial rules:** deload placement right, but a TT is maximal — strip the other
  quality session that week; ≤1 TT per 4–6 weeks. Distance: 5K goal → 3K TT; 10K/HM →
  5K TT; marathon → 5K or 30-min threshold test. (5K not 3K for HM: 3K over-rewards the
  speed-strong/endurance-limited HYROX profile.)
- **C12. Briefing needs 4 more slots** (beyond purpose/structure/feel/if-wrong):
  **execution cue** (one form focus; standing cadence cue on easy runs+strides — 152 spm
  flagged, progressive target 152→~160, never "jump to 180"); **terrain/venue** (hills:
  4–6% gradient 45–60s; 400s: track/measured flat; TT: flat repeatable); **fueling**
  (every run ≥75 min + every race-pace rehearsal: practice race-day gels/fluids —
  "dress rehearsal" is empty without it); **warm-up specificity** (R/I sessions: drills +
  2–3 strides in WU, not generic 10 min easy).
- **C13. Adaptive-loop guardrails:** bump signal = pace in/ahead of window **at appropriate
  HR/RPE** (pace:HR decoupling check — else it rewards racing your tempos); confound-correct
  via `enviro.py` (heat) + grade-adjusted pace or exclude flagged sessions; max +1 VDOT per
  4–6 weeks; no bumps in final 3 weeks, or while readiness/HRV trends down or illness-watch
  active; 5-session window must span ≥3 weeks; spec the "consistently behind" path too
  (hold / −1 / goal-infeasibility flag per C2).
- **C14. HYROX interference (running plan must respect load it doesn't own):** combined-
  modality ACWR from synced non-running activities + `rpe.json` sRPE; R/speed day placed
  furthest from heavy lower-body HYROX work (24–48 h interference); quality-day briefing
  failure-mode "legs dead from stations → run by RPE or swap with easy day"; post-HYROX-day
  runs target the slow half of the pace window.

**Engineering (plan-vs-code mismatches + 2 real bugs):**

- **E1. Keep type pools, kill param constants.** v1's "kill `pool[week%4]`" over-reached —
  pools do type rotation (fine); monotony lives in `_make_q1/q2` hardcoded kwargs.
- **E2. No plan.md generator exists** — plan.md is free-form Claude output
  (running-plan/SKILL.md step 7). Decision: add deterministic `paceforge plan-md`
  renderer (~60 lines in actions.py) so briefing rendering can't drift.
- **E3. BUG: `push.yml` has `contents: read` and no commit step** → `garmin_workout_id`
  written by `store.save_plan` (actions.py:591) is discarded in CI; dedup rests on the
  name+date sweep, and Phase-1 variant names change weekly → re-push orphans old
  workouts. Fix (permissions + commit plan.json) is a **prerequisite** for auto-sync.
- **E4. Skill-prompt drift:** `plan.yml:88-104` inline prompt + both SKILL.mds tell Claude
  to invent variety/notes — after Phase 1/2 they'd fight the engine. Update in the same
  PRs ("do NOT rewrite engine variety; add athlete-specific judgement only").
- **E5. `pace_key` must be stored per `WorkoutStep`** (steps only carry resolved numbers)
  — makes Phase-4 recalibration trivial; add it in Phase 1c while touching the model.
- **E6. Ladders must be tagged VO2MAX/THRESHOLD, never SPEED** — `_check_interval_lengths`
  caps SPEED reps at 120 s.

**Garmin feasibility (all six items FEASIBLE, zero fork patches):** the fork's Pydantic
models are `extra="allow"` — attach raw Garmin JSON fields directly, same pattern as the
existing pace.zone workaround.

- **G1.** Per-step notes: set `description` on the executable step; watch **does** display
  step notes at step start (FR 945/965 manuals). Cap ~200 chars/step. `stepAudioNote` /
  `wkt_step_name` unreliable — skip.
- **G2.** REST: fork already has `StepType.REST = 5`; pair with `conditionTypeKey:
  "lap.button"` (emit dict literally). ACTIVE → explicit interval mapping. Note: Track Run
  profile skips rest steps in pace/distance accounting.
- **G3.** HR targets: `workoutTargetTypeId 4 / heart.rate.zone` with **custom bpm bounds**
  (`targetValueOne/Two`), not `zoneNumber` (depends on athlete's Connect zone config).
  Needs `lactate_threshold_hr` plumbed into `WorkoutFactory` (`WorkoutFactory(paces,
  lt_hr=None)`).
- **G4.** Auto-sync: delete+re-upload already idempotent via `garmin_workout_id` (once E3
  fixed). In-place PUT `/workout-service/workout/{id}` possible via `self.client.client.put`
  — optimization, not blocker. ~6–12 calls/wk is nowhere near rate limits; real risk is
  stale GARMIN_TOKEN (sync.yml refreshes daily).
- **G5.** Extra constraints: **50 steps max per workout** (validate assert); watch stores
  ~20–200 workouts (another reason to sync only 2 weeks + delete stale); workout
  description limit 512 chars → bump cap 450→500, keep margin. Secondary targets
  (pace + HR) exist but fields undocumented — stretch, needs one export-and-inspect.

---

## What Runna does (v1 research, unchanged target)

**Variety:** fixed week skeleton, rotating insides. 4 long-run subtypes (Unstructured /
Progression / Blocks / Race-Pace Practice) — hard never twice running. Interval flavors
rotate (threshold reps, VO2 3–5 min, short speed, hills, strides, pyramids/ladders with
differentiated recoveries). Within-session pace ladders. Build-build-deload; long run
+10–15%/wk; opt-in time trials as milestone events. "Imperceptible gains" — paces creep
seconds/week as estimated race time improves.

**Descriptions:** every workout = purpose (physiology-lite why) + structure breakdown
with pace **windows** + feel (RPE language) + failure-mode advice. 45-article coaching
library behind the terms.

**Garmin:** watch does the coaching — per-step pace ranges, step-transition alerts,
next-2-weeks auto-synced Mondays, completed runs auto-link back. Ships recommended watch
settings (auto-lap OFF, audio prompts ON, open warm-up for track).

---

## The plan (v2)

Architecture unchanged (HYBRID, approved 2026-07-06): deterministic engine produces a
varied, structurally-sound, richly-briefed scaffold; `running-plan` panel skill adds
athlete-specific judgement; `validate.py` gates. PR-sized chunks below; each ships alone.

### Phase 0 — Confirm watch render (gate, 0 code, Victor, 10 min)
- [ ] Push one week; confirm on watch: min/km **range** per step, transition beeps,
  repeat groups render. Nothing in Phase 3 lands before this.
- [ ] Set auto-lap OFF + audio prompts ON (Runna's recommended settings; laps align to steps).

### Phase 1 — Structure + variety engine (complaint 1) — 4 PRs

**PR1 — Pace bands + step pace keys (S, ~150 loc)**
- `vdot.py`: `_BAND` as **percentage-derived** half-widths per C7 (≈±3–4%, asymmetric
  slow-side for I/R; easy = full table E range) + `TrainingPaces.band(key) -> (low, high)`.
- `_resolve_pace` (workouts.py:96) and `_build_steps` (planner.py:719-736) use `band()`;
  flat ±3 dies.
- `models/plan.py`: `TrainingPlan.pace_bands: dict[str, list[float]] | None` (additive;
  scalars stay for portal/back-compat); `WorkoutStep.pace_key: str | None` (E5).
- Old plan.json loads fine (optional fields); no migrator.

**PR2 — Structural soundness (M, the C1/C2/C3 fixes — do BEFORE variety)**
- Skeleton density rule (C1): ≤3 run days → hard long-run subtype consumes a quality slot.
- Goal-pace feasibility (C2): race pace derived from `target_time_seconds`; validate error
  when goal pace < T pace (unless explicitly overridden); copy names the right zone.
- Volume anchor (C3): week-1 volume from actual `weekly_mileage_km`, ramp keeps
  acute:chronic ≤ ~1.3; frequency-scaled long-run cap (C8): ≤30% @5+ days … ≤50% @3 days.
- `validate.py` rules for all three + 50-step Garmin limit (G5).

**PR3 — Variant library (L, ~450 loc)**
- New `src/paceforge/engine/variants.py`: plain dict `VARIANTS[slot_type] ->
  [(factory_method, kwargs), ...]`, **ordered by Canova levers** (more reps → longer reps
  → shorter recovery at fixed pace; recovery lever T/I only, never R — C9). Each variant
  carries `min_weekly_km` (C4). Selection: `idx = min(week_in_phase, len-1)`; deload →
  step back one index; partial reset after each deload (C9). `week_in_phase` from
  `members.index(wk_idx)` (planner.py:263); deload flag from
  `volume_prog[wk] < volume_prog[wk-1]`.
- Phase-correct tables (C5): base = hills/strides/fartlek/short T; build = I + cruise T;
  peak = T volume + race-pace; taper = short T + race-pace touches; R volume declines late.
- New/changed builders (workouts.py): merge `speed_400s/200s` → `speed_reps(reps, rep_m,
  rest_sec)`; `threshold_cruise_intervals` gains `rep_km`; new `ladder` (differentiated
  per-rung recoveries, tag VO2MAX/THRESHOLD per E6), `progressive_tempo(blocks,
  block_min)` (each block 5–10 s/km faster, uses bands), **`alternations(reps, on_km,
  float_km)`** (T/M floats — C6), **`steady_m_pace(km)`** (C6). Keep type pools; kill
  `_make_q1/q2` param constants + `_bump()` (E1); dispatch `getattr(factory, m)(**kwargs)`.
- Validate variety rule (C9 + eng §4): **no identical (type, name) quality session in
  consecutive weeks**; `benchmark`-tagged sessions repeat ≥3 weeks apart; easy repeats
  freely. Lands in the same PR so scaffold always passes.
- `plan.yml` prompt trimmed same PR (E4).

**PR4 — Long runs + milestones + strides (M, ~200 loc)**
- `long_run_blocks(distance_km, block_km, n_blocks)` builder (steady = M-band midpoint);
  unstructured = existing `long_run` with briefing changed (no new builder).
- Rotation (C10): hard subtypes alternate with unstructured; never same hard subtype
  consecutively; race-pace from mid-build; dress rehearsal 2–3 wks out; taper +
  post-rehearsal + cutback weeks = unstructured/easy only. Hard long run costs a quality
  slot at ≤3 days (C1).
- Time trial (C11): deload weeks ≥4 wks out, replaces BOTH quality slots that week
  (TT + easy only), ≤1 per 4–6 weeks; distance by goal (5K→3K, 10K/HM→5K, M→5K or 30-min
  threshold test). Ships always-on in scaffold; panel may remove.
- Strides: easy day nearest before Q1 gets `easy_with_strides` (Build/Peak); at 3 d/wk
  just the designated easy run (C15/graceful degradation).

### Phase 2 — Coaching content system (complaint 2) — 2 PRs

**PR5 — Briefings (M, ~300 loc, mostly template text)**
- `Workout.briefing: dict[str, str] | None` — keys: `purpose`, `structure`, `feel`,
  `if_wrong`, + per C12: `cue`, `venue`, `fuel` (≥75 min runs + race-pace rehearsals),
  `warmup` (R/I: drills + strides). Not all keys required per session.
- `src/paceforge/engine/briefings.py`: Python dict (no YAML/loader), keyed
  `(type_or_slot, variant | "default")` with default fallback — ~15 type templates + a
  handful of variant overrides; `str.format` slots ({reps}, {pace_window}, {phase},
  {week_role}…). Builders fill at construction (all slot values in scope).
- Standing cadence cue on easy/strides briefings: progressive 152→~160 spm (C12).
- HYROX interference lines (C14): quality-day `if_wrong` includes "legs dead from
  stations → RPE or swap"; post-HYROX-day target = slow half of window.
- `TrainingWeek.intro: str` — week's role in the arc, computed from (phase,
  week_in_phase, deload); replaces nothing, `focus` stays.
- SKILL.md step 4 rewritten (E4): notes ADD athlete-specific judgement (readiness, RPE
  history, cadence flag), never restate the briefing; Runna tone rules (name the feel,
  give the why, pre-empt the failure mode). Plan-level glossary of terms actually used.

**PR6 — Render (S–M)**
- Portal `showWorkoutSheet`: labeled briefing sections when present (~15 lines, `?.` reads).
- `_build_garmin_description`: purpose + structure first; cap 450→500 (G5).
- New `paceforge plan-md` deterministic renderer in actions.py (E2, ~60 loc); skills call
  it instead of free-forming plan.md.

### Phase 3 — Garmin enhancement (complaint 3) — 2 PRs, after Phase 0

**PR7 — Surgical client fixes (S, ~40 loc total per feasibility review)**
- Step map: ACTIVE → interval (explicit), REST → `StepType.REST`(5) + `lap.button` end
  condition (G2).
- Zero-width widen → athlete's real easy band (plumb `plan_paces` into `_to_garmin_step`,
  default-None fallback ±3 stays).
- Per-step notes: `step.description` → executable-step `description` (G1); briefing-derived
  rep lines ("Rep — hold 3:46–3:56, relax shoulders"), ≤200 chars.
- HR fallback: HEART_RATE steps → target id 4 with custom bpm bounds (G3);
  `WorkoutFactory(paces, lt_hr=None)` so hills can carry an LT-anchored HR range.
- Unstructured long runs push as single open/easy-band step; briefing says "watch stays
  quiet today — that's the point".

**PR8 — Auto-sync (S–M)**
- **Prerequisite: fix `push.yml`** — `contents: write` + commit plan.json so
  `garmin_workout_id` persists (E3).
- New `.github/workflows/autosync.yml` (NOT inside sync.yml — different cadence,
  same `paceforge-data` concurrency group): Mondays 06:00 UTC (after 05:00 sync),
  `paceforge autosync` → push `upcoming[:2]` weeks, delete stale Garmin copies of past
  completed workouts, commit plan.json.
- Portal push panel gets the watch-settings note (auto-lap OFF, auto-pause OFF, audio
  prompts ON, units = plan units).

### Phase 4 — Adaptive pacing loop (the Runna hook) — 2 PRs, after 1–3

**PR9 — Pace insights (M)**
- Extend `compliance.py` (not a new module): per matched quality workout, compare work-step
  target windows vs fastest-N km splits from `data/details/*.json` → per-workout
  `{pace_delta_sec, within_band}` in `completion_metrics`; `pace_status` over last 5
  quality sessions **spanning ≥3 weeks** (C13) → ahead / on-point / review in
  `fitness.json`; portal chip on Plan page.
- Guardrails (C13): require sane HR/RPE for "ahead" (pace:HR decoupling or logged RPE ≤
  expected); enviro/heat correction via existing `enviro.py`, exclude flagged sessions.

**PR10 — Recalibration (M)**
- `paceforge recalibrate` action + workflow_dispatch + portal accept/reject button:
  re-derive `pace_bands` + step targets via stored `pace_key` for weeks
  `scheduled_date >= today` only — structure never mutates (Runna's rule).
- Rate limits (C13): max +1 VDOT per 4–6 weeks; frozen final 3 weeks; blocked while
  readiness/HRV down or illness-watch active. TT result (PR4) is a first-class input.
- Behind-path: consistent "review" → propose hold/−1 VDOT or goal-infeasibility flag (C2).

---

## Test plan (per engineering review)

- PR1: `band()` values/order, easy==table range, `pace_bands` populated, old plan.json
  fixture loads, step-pace envelope still passes.
- PR2: skeleton rule at 3 vs 5 days; goal<T validate error; week-1 ACWR; long-run cap by
  frequency.
- PR3 (`test_variants.py`): every variant dispatches; Canova ordering invariant (work
  volume non-decreasing); deload index step-back; min_weekly_km gating; no consecutive-week
  identical key on a generated 12-wk plan; ladder/pyramid/progressive/alternation step
  shapes; ladders never SPEED-tagged.
- PR4: rotation invariants (no hard subtype twice running, race-pace absent in Base,
  taper unstructured); TT only in eligible deloads, strips Q2.
- PR5 (`test_briefings.py`): every produced (type,variant) resolves a briefing; no
  unresolved `{slot}`; Garmin description ≤500.
- PR7 (`test_garmin_steps.py`): ACTIVE/REST ids, easy-band widen, step description
  propagation, HR target emission, ≤50 steps.
- PR8 (`test_autosync.py`, mocked client): exactly 2 upcoming weeks; stale-cleanup
  delete-by-id; second run idempotent.
- PR9/10 (`test_compliance.py`): pace delta vs fixture details; status thresholds;
  missing detail file → no crash; recalibrate touches only future weeks, respects
  rate-limit/readiness blocks.

## Risk register

| Risk | Mitigation |
|---|---|
| push.yml discards garmin_workout_id (live bug) | Fix permissions+commit in PR8 prerequisite; until then dedup = name sweep only — don't rename-and-repush |
| Old accepted plan.json vs new code | All new fields optional; recalibrate skips steps without `pace_key`; regenerate rather than migrate |
| Skill/prompt fights the engine post-Phase 1/2 | plan.yml prompt + SKILL.md updated in same PRs (E4) |
| Validate as push gate: pre-1a plans could fail new rules | Rules scoped (consecutive weeks); scaffold guaranteed by tests; stale plan → regenerate |
| Watch render assumptions (step notes, REST, HR) | Phase 0 gate first; each PR7 checkbox independently revertible |
| Pages CDN staleness (old HTML + new JSON) | All portal reads `?.`-guarded optional |
| GARMIN_TOKEN staleness breaks Monday autosync | sync.yml already refreshes daily 05:00; autosync runs 06:00 after it |

## Sizing & order

PR1 → PR2 → PR3 → PR4 (Phase 1) → PR5 → PR6 (Phase 2) → PR7 → PR8 (Phase 3, gated on
Phase 0) → PR9 → PR10 (Phase 4). Phase 0 anytime — do it first.

Structural fixes (PR2) deliberately precede variety (PR3): a varied plan that injures the
athlete in week 3 is worse than a boring one.

Not doing (YAGNI, revisit on demand): guided audio warm-ups, community/gamification
(Runna Score), LLM-generated plans (HYBRID stays), Connect IQ data field, FIT sideload,
secondary pace+HR targets (undocumented fields — stretch after one export-and-inspect),
in-place PUT workout update (delete+re-upload already idempotent), exact step↔lap
alignment in pace insights (fastest-N-splits approximation first).
