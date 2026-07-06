# PaceForge Deep Review — 2026-07-06

Three complaints investigated: (1) running plans are poor/repetitive, (2) workouts
aren't Garmin-ready (no pacing), (3) HYROX analysis page vanished. Findings + rebuild plan.

---

## TL;DR

| # | Complaint | Root cause | Fix size |
|---|-----------|-----------|----------|
| 1 | Plans simple & repetitive | Fixed template + `week%4` rotation, **hardcoded** workout params, no progression, no real periodization, rich data thrown away. The "AI-powered" docstring is a lie — no LLM runs; the `coach` skill (the actual AI) never runs automatically. | **Rebuild** (engine) |
| 2 | Not Garmin-ready | Already pushes a *structured* workout (not a note), but with `speed.zone`(id 5) instead of `pace.zone`(id 6) → watch shows km/h speed not min/km pace; **and** easy/WU/CD steps stored with `target_low==target_high` → zero-width = no-op target. | **Surgical** (~15 lines) |
| 3 | HYROX page dropped | Not dropped — **one-char nav bug**. Desktop sidebar renders `NAV.slice(0,5)`; a later commit prepended `today` at index 0, shoving HYROX to index 5, off the slice. Mobile filters differently so it still shows there. | **Done** (fixed) |

---

## 1. Why the plans are poor

**The generation path is 100% deterministic template + rotation. No intelligence.**

- `planner.generate_plan()` docstring claims "AI-powered (default when OpenAI key available)". **That branch does not exist** — it unconditionally calls `_generate_template_plan` (`planner.py:163`). The only "AI" is the manual `coach` skill (`.claude/skills/coach/SKILL.md`) that a human-driven Claude session runs on top. In normal automated use, the owner sees the bare skeleton — the coach step never fires.
- **Workout parameters are hardcoded constants.** `_make_q1` always emits `vo2max(5×3.5min)`, `speed_400s(8)`, `hills(8)`, `fartlek(40min)`; `_make_q2` always `threshold_cruise(4×6min)`, `race_pace(4×1km)` (`planner.py:420-466`). Week 4 == week 8, byte for byte. **Zero week-over-week progression.**
- **Type rotation is a length-4 static list** cycled `pool[week % 4]` (`planner.py:66-91`). That's the whole menu inside a phase.
- **No intensity periodization.** Phases only swap *which pool* is read; paces frozen at generation, never re-derived. Focus text = 4 canned strings recycled by `week%4`.
- **Volume is one-size-fits-all.** `peak_weekly_km` is a fixed table lookup, not anchored to the athlete's actual `weekly_mileage_km`. A 60 km/wk runner can start at ~26 km.
- **HYROX gaps:** only **1 station day/week** (the repo's own `limiters.py` says 2+); rotates just 3 of 8 stations (weakest-2 focus drops the rest); the detailed `hyrox_intermediate.yaml week_template` is **dead code** — never read for non-race weeks; brick volume never progresses.
- **Rich data computed then ignored by the planner:** readiness/HRV/sleep/body-battery, running dynamics (cadence/GCT/power), endurance-score/training-status, recent activities, `target_time_seconds` (goal), and the *entire* limiter/fade/station analysis. Only weakest-2 station names reach `generate_plan`.

Evidence files: `planner.py` (`_build_varied_week`:291, `_make_q1/q2/long`:420-476), `limiters.py`+`strength.py` (analysis that never reaches the planner), `actions.py:430`.

## 2. Why Garmin doesn't pace you

**Correction to the initial assumption: it IS a structured workout, scheduled to the calendar, with per-step m/s targets and repeat groups.** The wiring is sound. Two concrete defects stop the pacing:

1. **Wrong target key.** `client.py:1098` hardcodes `speed.zone` / id **5** for every running step. Garmin's running pace target is `pace.zone` / id **6**. `speed.zone` renders as a km/h speed target, not the min/km range you expect; on several running-workout screens the pace guidance simply doesn't surface. The pinned garminconnect fork **doesn't even define a `pace.zone` constant** (mislabels id 6 as `OPEN`, `workout.py:67-75`) — that's the smoking gun for why it was never wired. Fix: emit id 6 + key `pace.zone`; the m/s values are already correct (`1000/sec_per_km`).
2. **Zero-width easy zones.** Easy/warmup/cooldown/recovery steps are stored with `target_low == target_high` (e.g. both 290 s/km) → `targetValueOne == targetValueTwo` → Garmin treats it as a degenerate no-op range. The *real* easy range exists in `TrainingPaces` (`vdot.py:79-80`, e.g. 270.6–298.6 s/km for VDOT 54.6) but is thrown away when the steps are written. This is the **#1 real-world cause** of "no pacing" and hits all the easy volume.

Minor: `ACTIVE`/`REST` step types fall through to `interval` in the map (`client.py:1128`); `IntensityTarget.HEART_RATE` steps silently become `no.target`.

### Verified Garmin pace-target format (for the fix)
- Pace targets are stored in **m/s**: `m_per_s = 1000 / seconds_per_km`. Faster pace = higher m/s. 4:00/km→4.1667, 4:10/km→4.0000, 5:00/km→3.3333.
- Both `targetValueOne`/`targetValueTwo` mandatory, both > 0, treated as unordered `[min,max]`.
- Garmin keys off the numeric **ID**, not the string — must send id 6 explicitly (don't trust the fork's `TargetType.OPEN` label).
- Reference payload + full enum table saved inline in this review's research (pace.zone=6 confirmed against live community payloads: `3.333333/3.030303` = 5:00–5:30/km).

## 3. The HYROX page — already fixed

Whole page is coded and deployed: nav entry, `renderHyroxPage` (`web/index.html:2788-3360`) with race cards, percentile radar, pacing waterfall, race simulator, station fade, next-race projection; data pipeline (`build_site_data.py` → `hyrox_analysis.json`) intact with 7 imported races. It just fell off the **desktop** sidebar because `NAV.slice(0,5)` wasn't updated when `today` was prepended (commit `af8269b`).

**Fixed** on branch `feat/typed-splits`: `NAV.slice(0,5)` → `NAV.slice(0,-1)` (shift-proof — all training items bar trailing Settings). Needs to reach `master` for the live site (Pages deploys from master).

---

## Rebuild plan

### Quick wins (do now, low risk)
- **A. Nav fix** — done, needs merge/push to master to go live.
- **B. Garmin pace targets** — `client.py`: swap `speed.zone`/5 → `pace.zone`/6; when `target_low==target_high` widen to the real `TrainingPaces` easy range (or ±3 s/km); add ACTIVE/REST to the step-type map. Update `test_garmin_steps.py`. **Requires one on-watch confirmation from Victor** (only he can see the watch render).

### The plan engine (the real work — complaint #1)
Encode a coach-grade generator. Highest-leverage rules from the research:

1. **VDOT pace engine** — race/TT time → VDOT → E/M/T/I/R bands from Daniels tables (deterministic lookup; re-test to update). Bands, not single values.
2. **80/20 polarized structure** — 2–3 quality sessions + 1 long run/week; hard days never back-to-back.
3. **Per-zone volume caps** — Threshold ≤10%, Interval ≤8%, Rep ≤5% of weekly km; I reps ≤5 min; R reps ≤2 min; long run ≤25–30% of week.
4. **Phase arc tied to race date** — base→build→peak→2–3wk taper; **3:1 build:deload**; keep ACWR ~0.8–1.3 (acute:chronic beats the flat 10% rule).
5. **Progression via Canova's 3 levers** at fixed pace — more reps / longer reps / shorter recovery, stepped week to week. Kills the repetition.
6. **HYROX overlay** — replace one quality run with a **compromised-running/hybrid** session (run→station→run), 1–2 strength days, rotate all 8 stations weighted to the weak ones, progress brick volume across build. Drive run targets from **compromised 1 km splits** (fresh pace + 25–40 s/km; total run time ≈ 5K × 1.8), even-pacing race model.
7. **Feed the athlete data back in** — route `rank_limiters`/`strength.py`/readiness into generation, anchor volume to actual `weekly_mileage_km` + recent activities, use `target_time_seconds` for goal pace + feasibility check.

**Architecture question (yours to decide):** how does "the AI" build plans —
- **Deterministic engine** (encode the rules above in `planner.py`; no LLM; reproducible/testable; fits the current no-key serverless design), or
- **LLM-in-CI** (wire a real Anthropic API call + key secret into the sync/plan workflow so plans are model-generated each cycle — literal "use AI" but adds a keyed dependency + cost + breaks the no-key ethos), or
- **Hybrid** (deterministic engine produces a genuinely strong scaffold *with* progression/periodization, and the existing `coach` skill layers judgement — make the automated skeleton good, keep Claude-as-coach for personalization).

Sources: Daniels/VDOT, Pfitzinger, Hansons, Norwegian singles, Seiler 80/20, Canova %-based; HYROX — Red Bull compromised running, Rox Lyfe, HyroxDataLab pacing tables. Full citations in the research transcript.
