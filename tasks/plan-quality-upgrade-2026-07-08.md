# Plan Quality Upgrade — Runna-Level Running Plans (2026-07-08)

Victor's three complaints, verified against the code and benchmarked against Runna
(+ Garmin DSW, TrainingPeaks, NRC):

| # | Complaint | Root cause (verified) | Verdict |
|---|-----------|----------------------|---------|
| 1 | Plans boring — same run every week, no varied paces/times | Session types still picked from **static length-4 pools** `pool[week % 4]` (`planner.py:82-108,370-373`); workout params **hardcoded constants** (`planner.py:445-495` — vo2max always 5×3.5min, 400s always ×8, fartlek always 40min); only progression is a small `_bump()` rep-count nudge (`planner.py:440`). Long-run subtypes exist but rotate mechanically. Non-easy step targets are a fake **±3 s/km band** around one pace (`workouts.py:96`, `planner.py:727-736`) — nothing like Runna's real pace windows and within-session ladders. | Engine upgrade |
| 2 | Descriptions thin — couple of lines, no stages/why | `Workout.description` = 1–2 **hardcoded sentences per generator**, identical every week (`workouts.py:118,152,186,224,293,385,500,543`). `notes` filled by the running-plan skill but with no content standard — no purpose/structure/feel/failure-mode framework. No week-intro narrative beyond 1 canned focus line. | Content system |
| 3 | Not Garmin-enhanced — watch just "runs" | `pace.zone` id-6 fix IS live (`client.py:1119-1130`, master eba9e41) but **never confirmed on watch**. Remaining gaps: ACTIVE/REST steps fall through to `interval` (`client.py:1160-1162`); zero-width targets widened by generic ±3 s/km instead of real `TrainingPaces` easy band (`client.py:1114-1115`); HR-target steps silently become `no.target` (`client.py:1173-1177`); no per-step naming so reps show as anonymous "interval"; push is manual per-week, no auto-sync of upcoming weeks. | Surgical + confirm |

Research inputs: repo map (this session), Runna/competitor research (this session, primary
sources: support.runna.com, runna.com, Garmin, TrainingPeaks), prior
`tasks/deep-review-2026-07-06.md` (HYBRID architecture approved and shipped — deterministic
scaffold + `running-plan` panel skill via `plan.yml`).

---

## What Runna actually does (the target)

**Variety** — fixed week skeleton, rotating insides:
- **4 long-run subtypes** rotated so a hard long run never repeats two weeks running:
  Unstructured (run to feel, zero targets — deliberately "switch off"), Progression
  (pace steps up every ~3km), Blocks (easy + Zone-3 steady segments), Race-Pace Practice
  (goal-pace intervals inside the long run). This is their #1 anti-monotony device.
- **Interval flavors rotate**: threshold reps (2–5km, jog recovery), VO2 intervals
  (3–5min), short speed (200–400m, full recovery), hills, strides bolted onto easy runs,
  pace **pyramids/ladders** with differentiated recoveries (NRC: 1:00 mile-pace/2:00
  5K/3:00 10K and back down; 45s rest after 5K reps, 1:00 after mile reps).
- **Within-session pace ladders**: real Runna tempo = 6 laps each faster (7:00→6:55→6:40→6:30/mi).
- **Build-build-deload blocks**, long run +10–15%/wk, opt-in **time trials** in deload
  weeks as milestone/confidence events; race-pace rehearsal doubles as dress rehearsal.
- **Imperceptible gains**: pace targets creep a few s/km as estimated race time improves —
  reviewers single this out as the hook.

**Descriptions** — every workout card ships four things: **purpose** (physiology-lite
"why"), **structure breakdown** (WU → reps with pace windows → CD), **feel** (RPE +
"comfortably hard" language), **failure-mode advice** ("if tempo feels too hard, slow
5–10 s/km rather than walking — keeps the stimulus alive"; "on hills/heat switch to
RPE"). Paces always **windows, not single numbers** (target 7:00, range 6:50–7:10).
45-article coaching library backs the terms used in briefings.

**Garmin** — the watch does the coaching: native structured workout, per-step pace
range, vibrate at step transitions, speed-up/slow-down alerts, next-2-weeks auto-synced
every Monday, completed run auto-links back to the planned session. Ships recommended
watch settings (auto-lap OFF so laps align to steps, audio prompts ON, open warm-up for
track days).

---

## The plan

Architecture unchanged (HYBRID, approved 2026-07-06): deterministic engine produces a
genuinely varied, richly-described scaffold; the `running-plan` panel skill personalises
on top; `validate.py` gates. Order below = dependency order; each phase ships alone.

### Phase 0 — Confirm the watch render (gate, 0 code)
- [ ] Victor pushes one week (`push.yml` or `paceforge push --week N`) and confirms on
  the watch: pace shown as min/km **range** per step, step transitions beep, intervals
  show as repeat groups. The id-6 fix was diagnosed blind; nothing else in Phase 3 is
  worth building until this renders right.
- [ ] While there: set auto-lap OFF + audio prompts ON and note the difference (Runna's
  recommended settings — laps then align to workout steps).

### Phase 1 — Variety engine (complaint 1, the big one)

**1a. Session-variant library replaces hardcoded params** (`planner.py`, `workouts.py`)
- Replace `_make_q1/_make_q2/_make_long_run` constants with a variant table per
  workout type: rep distance/count/recovery options keyed by phase + week-in-phase.
  E.g. VO2: {5×3min, 6×3min, 5×4min, 4×5min, 3-2-1 ladder}; speed: {8×400, 10×400,
  6×600, 12×200, 200/400 pyramid}; threshold: {4×6min cruise, 3×2km, 2×15min tempo,
  20-30min continuous, progressive tempo ladder}.
- New step builders in `WorkoutFactory`: **pyramid/ladder** (differentiated recoveries
  per rep pace, NRC-style) and **progressive tempo** (3-4 blocks, each 5-10 s/km
  faster — the Runna lap-ladder session).
- Selection rule: within a phase, walk the variant table by **Canova's three levers**
  (more reps → longer reps → shorter recovery) at fixed pace, so week N+1 is always a
  visible step up from week N, never a repeat. Kill `pool[week % 4]`.
- `validate.py` new rule: **no two non-easy sessions in a plan may have identical
  (type, variant, params)** — makes monotony a CI failure, not a review nit.

**1b. Long-run rotation done properly** (`planner.py`)
- Adopt Runna's 4 subtypes explicitly: add **Blocks** long run (easy + steady Z3
  segments) to the existing long/progressive/race-pace builders.
- Rotation rule: alternate hard (progression/blocks/race-pace) with **unstructured**
  ("no targets — run to feel, chat, switch off"; steps carry easy band only), and never
  the same hard subtype in consecutive weeks. Race-pace subtype only from mid-build.

**1c. Real pace windows** (`vdot.py`, `workouts.py`, `plan.py`)
- `TrainingPaces` already holds real easy bands; extend to **per-zone bands** (E/M/T/I/R
  low+high from the Daniels table, ±ranges per zone: T ±4s, I ±5s, R ±3s, M ±5s — tune
  once) and use them in `_resolve_pace`/`_build_steps` instead of the flat ±3.
- Plan-level pace fields become band pairs (additive fields, keep old scalars for
  back-compat in portal/plan.md).

**1d. Milestone workouts** (`planner.py`)
- Insert an opt-in **time trial** (3K or 5K by event) in deload weeks ≥4 weeks out —
  doubles as the pace-recalibration input (Phase 4) and Runna's "excitement and
  momentum" event.
- Tag race-pace rehearsal long runs as **dress rehearsal** in the description (fueling,
  kit, warm-up routine).

**1e. Strides bolt-on** — easy runs in build/peak get 4-6×20s strides appended
(generator exists: `easy_with_strides`), scheduled the day before quality sessions.

### Phase 2 — Coaching content system (complaint 2)

**2a. Structured description, not one string** (`models/plan.py`, `workouts.py`)
- `Workout` gains a `briefing` block (or convention inside `description`):
  **Purpose** (why this session, this week — physiology-lite) · **Structure** (step-by-
  step with pace windows: "10min WU easy 4:30-4:57 → 5×4min @ 3:46-3:51, 2:30 jog
  recoveries → 10min CD") · **Feel** (RPE + plain language: "comfortably hard — last rep
  should feel like you had one more") · **If it goes wrong** (per-type failure-mode
  advice: tempo too hard → slow 5-10 s/km, don't walk; hills/heat → switch to RPE).
- Engine fills all four from a **content library**: per (type × variant × phase)
  template with slots for paces/reps/phase context. Deterministic, testable, ~40-60
  templates. This is what makes the *scaffold* readable before the panel even runs.
- Week gains an `intro` paragraph: this week's role in the arc ("Build week 2 of 3 —
  threshold volume peaks here; next week is a deload"), replacing the 4 canned focus
  strings (`planner.py:111-132`).

**2b. Panel skill upgraded to the same standard** (`.claude/skills/running-plan/SKILL.md`)
- Step 4 rewritten: notes must ADD athlete-specific judgement on top of the briefing
  (readiness, cadence flag, RPE history, "your week-3 tempo felt 8/10 so this one holds
  pace") — never restate the briefing. Give the skill the Runna tone rules: name the
  feel, give the why, pre-empt the failure mode.
- Plan-level: `rationale` keeps the good current form; add a short glossary of the
  coaching terms the plan actually uses (T/I/R pace, cruise intervals, strides).

**2c. Render everywhere** — `plan.md` generator + portal show the 4-part briefing;
`_build_garmin_description` (`client.py:987-1062`) selects Purpose + Structure lines
first within the 450-char cap.

### Phase 3 — Garmin enhancement (complaint 3)

- [ ] **Step-type map**: add ACTIVE→interval (explicit), REST→rest (`client.py:1160`).
- [ ] **Real easy widening**: replace ±3 s/km zero-width widen (`client.py:1114`) with
  the athlete's actual `TrainingPaces` easy band (Phase 1c makes this trivial).
- [ ] **Per-step naming/descriptions**: every step carries its coaching line ("Rep 3/5 —
  hold 3:46-3:51, relax shoulders") so the watch/Connect shows meaningful step text, not
  bare "interval".
- [ ] **HR fallback**: hills + any HR-target steps get an HR-zone target (zone from
  `lactate_threshold_hr`) instead of silently `no.target` (`client.py:1173-1177`).
- [ ] **Auto-sync upcoming weeks** (Runna's Monday sync): extend `sync.yml` (or a small
  scheduled workflow) to push/refresh the next 2 weeks of the accepted plan and delete
  completed/stale ones — kills the manual per-week Push button as the only path.
- [ ] **Watch-settings note** in the portal push panel: auto-lap OFF, auto-pause OFF,
  audio prompts ON, units = plan units.
- [ ] Unstructured long runs push as a single open/easy-band step on purpose — document
  that in the briefing ("watch will stay quiet today, that's the point").

### Phase 4 — Adaptive pacing loop (the Runna hook, do after 1-3)

- **Pace-insights-lite**: after each completed quality session, `matching.py` +
  `compliance.py` already link activity↔workout; add a check of actual vs target windows
  over the last ~5 quality sessions → status (on-point / ahead / review) surfaced in the
  portal + weekly review.
- **Accept/reject recalibration**: consistent "ahead" → propose a VDOT bump (or use the
  Phase 1d time-trial result); athlete accepts via portal button → re-derive bands for
  REMAINING weeks only (structure untouched — Runna's rule: adaptivity never silently
  mutates the plan). This delivers the "imperceptible gains" pace creep.
- Feeds on data already synced (`recent_activities`, `data/details/*.json`) — no new
  Garmin surface needed.

---

## Sizing & order

| Phase | Size | Depends on |
|---|---|---|
| 0 watch confirm | 10 min (Victor) | — |
| 1 variety engine | L (~3-4 sessions: variant tables, 2 new builders, rotation, bands, validate rule, tests) | — |
| 2 content system | M (~2 sessions: library, model field, skill prompt, renderers) | 1c for windows in copy |
| 3 Garmin | S (~1 session; each checkbox independent) | 0 (confirm), 1c (easy band) |
| 4 adaptive loop | M (~2 sessions) | 1 (variants), 0 |

Suggested execution: **0 → 1 → 2 → 3 → 4**. Phases 1+2 are what changes how plans feel;
3 is what changes the watch; 4 is what keeps it motivating after week 3.

Not doing (YAGNI, revisit on demand): guided audio warm-ups, community features, Runna
Score gamification, LLM-generated plans (HYBRID stays — deterministic scaffold, panel
judgement), Connect IQ custom data field, FIT sideload.
