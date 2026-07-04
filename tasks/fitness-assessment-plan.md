# PaceForge Fitness 2.0 — Athlete Assessment & Coach Feedback Plan

> **STATUS: SHIPPED (July 2026).** All phases are implemented; this file is kept as
> design rationale. Where each phase landed:
> Phase 0 → `data/history.jsonl` + `scripts/repair_history.py` (null-row protection) ·
> Phase 1 → `engine/durability.py` (+ `engine/curves.py` pace curves, `engine/enviro.py`
> heat adjustment, effective VO2max) ·
> Phase 2 → `engine/load.py` (incl. sRPE load from `data/rpe.json`) +
> `engine/compliance.py` plan-vs-actual ·
> Phase 3 → `hyrox/benchmarks.py` cohort benchmarks + HYROX builders in
> `engine/workouts.py` + `engine/adaptation.py` (`paceforge adapt`) ·
> Phase 4 → `engine/limiters.py` → the `coach_input` contract the coach skill consumes.

Grounded in 3 parallel sports-science research streams (running performance/economy/endurance;
load/recovery/wellbeing; HYROX-strength + coaching engine). Feasibility tags:
**[NOW]** computable from current data · **[SERIES]** uses the HR/pace time-series we already store ·
**[HISTORY]** needs a daily snapshot history we must start storing · **[INPUT]** needs a small one-time user benchmark.

## The core finding
Current analytics measure **capacity** (VDOT, VO2max, threshold, economy grades) well. Three gaps:
1. **Durability** — holding pace under accumulating fatigue. The single biggest HYROX determinant. Computable NOW from the time-series + HYROX splits we already capture.
2. **Trends over time** — fitness/fatigue/form, HRV baseline, sleep debt. Needs a daily history we don't yet keep.
3. **Actionable prioritization** — turning numbers into "your top 3 limiters + what to do this week." The product's real value.

---

## Phase 0 — Foundations (prerequisite)
- **Fix 2 data-quality bugs** (they corrupt zone math, TRIMP, thresholds):
  - `max_hr = 230` is a garbage default → derive true HRmax from observed activity max-HR (or 220−age) and store it.
  - `lactate_threshold_speed = 0.386 m/s` is a units bug → fix normalization. *(Fixed —
    the canonical `normalize_lt_speed` now lives in `engine/vdot.py`.)*
- **Start storing daily history** → `data/history.jsonl`, one slim row appended per sync: date + readiness, training_status, training_load_7day, load_focus, hrv_status, hrv_last_night_ms, resting_hr, body_battery hi/lo, sleep_score + stages, stress avg/hi, weekly_mileage. Backfill an `activity_load` series from existing `activities.json` (TE + HR + duration are already there). **Every day not stored is permanently lost** — ship this first.

## Phase 1 — Running engine & durability (high-value, computable now)
- **Compromised-running fade** [NOW/SERIES] — pace fade within a session and across the 8 HYROX runs. *The* HYROX metric.
- **Aerobic decoupling, done right** [SERIES] — first-half vs second-half efficiency (EF) on steady runs; upgrade the crude "cardiac drift." <5% = strong.
- **Efficiency Factor (EF) trend** [NOW] — speed (or power) per heartbeat across easy runs = the headline "am I getting fitter" chart.
- **Critical Speed / D′ (+ Critical Power / W′ from running power)** [SERIES] — athlete-specific sustainable speed + anaerobic reserve; modern successor to "VDOT + fudge."
- **HR recovery (HRR60)** [SERIES] — HR drop 60s after peak; clean fitness/fatigue marker + deload trigger.
- **80/20 intensity distribution** [NOW] — from HR-zone time we already store; flag grey-zone creep. Highest-ROI behavioral fix.
- **Negative-split / pacing personality** [NOW] — 2nd-half vs 1st-half pace; coaches the proven HYROX pattern.
- **vVO2max & economy-vs-pace curves** [SERIES] — turn static cadence/GCT/vert-osc grades into trends-with-speed-and-fatigue.

## Phase 2 — Load, recovery & wellbeing (needs Phase 0 history)
- **Daily load (Banister TRIMP) + aerobic/anaerobic split** [NOW per-activity / HISTORY to trend].
- **CTL / ATL / TSB** (fitness / fatigue / form) [HISTORY] — EWMA 42d/7d; race-day form +15..+25; train in TSB −10..−30.
- **HRV baseline + normal range (±0.5 SD) + the train-hard/back-off rule** [HISTORY] — RCT-proven readiness signal.
- **HRV CV, resting-HR trend, HRV↓/RHR↑ coupling** [HISTORY] — strongest combined fatigue/illness detector.
- **Sleep debt (14d) + architecture (deep/REM%)** [NOW/HISTORY].
- **Monotony & strain (Foster), CTL ramp rate, single-session spike vs 30-day max** [HISTORY] — best-evidenced running-injury guardrail.
- **Overtraining/illness early-warning composite** [HISTORY] — multi-marker, individualized; the safety net.
- **Daily readiness composite (ours) + surface Garmin native** (Training Status, Load Focus, Training Readiness, Recovery Time) [NOW] — show Garmin's verdict + our transparent metrics side by side.
- *ACWR: keep but only uncoupled/EWMA, never a standalone gate (2020–25 evidence: not a valid injury predictor).*

## Phase 3 — Strength / HYROX (honestly gated on ~5 inputs)
- **5 one-time benchmarks** [INPUT], re-tested every 6–8 wks: max unbroken wall balls, max unbroken sandbag lunges, 500m row + 500m SkiErg, a max-effort 60s station, optional 1–2 strength anchors. HR-from-a-strength-session **cannot** measure strength — UI must say "estimate — enter benchmarks to unlock."
- **Station percentile radar** [NOW w/ a HYROX result] — names the 2–3 weakest stations to train.
- **Hybrid balance score** [NOW run side / INPUT strength side] — run-vs-strength identity dial that steers the block.
- **Anaerobic capacity (CP/W′ + anaerobic-TE trend), strength-endurance proxies, transition/roxzone cost** [NOW/SERIES/INPUT].

## Phase 4 — Coach feedback engine (the payoff)
- **Limiter-ranking engine** [NOW] — score every metric vs goal/norms, weight by HYROX time-impact, **gate by readiness**, output **top 3 limiters max** with cited evidence.
- **Structured metric object** → the existing Claude coach skill consumes it (math stays deterministic in code; LLM does judgement). Output sections: headline diagnosis · top-3 limiters w/ evidence · this week (1–2 named sessions, pace/HR/power targets, readiness-gated) · this block (theme + re-test date) · what we can't see yet (data-gap CTAs) · one thing NOT to do.
- **Guardrails:** concurrent-training spacing (≥6h, non-consecutive), max 3 actions, readiness overrides fitness gaps, confounders annotated not alarmed.
- Wire into existing `coach.yml` / `analyze.yml` (already working end-to-end).

## Redesigned Fitness page
Sections: **Coach's Take** (limiter callout + this-week actions, top) → **Engine** (VO2max/vVO2max/CS/threshold + EF trend) → **Durability** (decoupling, compromised-run fade, HRR) → **Training Distribution** (80/20, load split) → **Load & Recovery** (CTL/ATL/TSB, HRV, sleep, readiness) → **Strength/HYROX** (balance, stations, benchmarks) → **Trends** (everything over time).

## Build order recommendation
Phase 0 first (unblocks all). Then Phase 1 (most value from existing data, no waiting). Phase 2 in parallel — but it only gets meaningful ~6 weeks after Phase 0 ships, so start the storage immediately. Phase 4 after 1–2 (needs metrics to rank). Phase 3 whenever you'll enter benchmarks.
