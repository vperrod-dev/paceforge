# PaceForge Test Coverage Analysis & Implementation Plan

**Date:** 2026-07-28  
**Overall Coverage:** 72% (469 passed, 1660 untested statements)  
**Status:** 8 critical gaps identified; 5 test skeleton files provided

---

## Executive Summary

PaceForge has solid core logic coverage but **critical entry points untested:**

1. **CLI (0%)** — All 8 commands untested; user-facing entry point
2. **Analytics (82% untested)** — Core coaching calculations never exercised
3. **Scraper (65% untested)** — Web parsing fragile, failure modes unknown
4. **Garmin Client (57%)** — Auth, sync, error paths need coverage
5. **Actions (26% untested)** — Business logic (sync, push, adapt, scaffold) untested end-to-end

**Risk Profile:** High—untested paths are production-critical (sync loops, file I/O, Garmin API, plan generation).

---

## Coverage by Module (Ranked by Risk)

| Module | Coverage | Statements | Gap | Risk |
|--------|----------|------------|-----|------|
| **cli.py** | 0% | 132 | 132 | CRITICAL: main() dispatch |
| **analytics.py** | 18% | 611 | 503 | CRITICAL: all compute functions |
| **scraper.py** | 35% | 262 | 170 | HIGH: web parsing |
| **garmin/client.py** | 57% | 644 | 280 | HIGH: API error handling |
| **hyresult.py** | 70% | 74 | 22 | MEDIUM: obstacle race model |
| **store.py** | 75% | 207 | 52 | MEDIUM: atomic I/O |
| **actions.py** | 74% | 748 | 192 | HIGH: business workflows |
| **planner.py** | 80% | 406 | 81 | MEDIUM: plan generation |
| **insights.py** | 80% | 128 | 25 | LOW: readiness logic |
| **validate.py** | 84% | 156 | 25 | LOW: plan validation |
| **compliance.py** | 88% | 133 | 16 | LOW: pace compliance |
| **strength.py** | 88% | 207 | 24 | LOW: strength analysis |
| **curves.py** | 90% | 77 | 8 | LOW: aerobic curves |

---

## Critical Gaps (0-60% coverage)

### 1. CLI Commands (0% | 132 stmts)

**Entry Point Status:** ❌ UNTESTED

**What's Missing:**
- `main()` argument parsing (lines 20-182)
- Command dispatch to actions (login, sync, plan, push, autosync, adapt, recalibrate, garmin-delete)
- `_emit()` JSON output serialization
- Error handling (RuntimeError/KeyError at lines 178-180)

**Why Critical:**
- CLI is sole user-facing interface
- Silent failures → data loss (sync not running, plan not pushed)
- MFA flow not validated

**Test File:** `tests/test_cli_commands.py` ✅ Provided
- 20+ command routing tests
- Output formatting (JSON, text, Telegram)

---

### 2. Analytics (18% | 611 stmts, 503 untested)

**Entry Point Status:** ❌ UNTESTED

**What's Missing:**
All 11 public compute functions lack unit tests:
- `_estimate_vdot()` — VDOT prediction from race results (no VDOT accuracy check)
- `_predict_race_time()` — Riegel formula (binary search never exercised)
- `compute_athlete_snapshot()` — Summary aggregation (level classification untested)
- `compute_aerobic_analysis()` — VO2 trends (all thresholds untested)
- `compute_running_economy()` — Efficiency grading (calc untested)
- `compute_load_recovery()` — CTL/ATL/TSB formulas (composite risk untested)
- `compute_race_predictions()` — Multi-distance forecasts (pace ordering untested)
- `compute_hyrox_predictions()` — Obstacle race estimates (fade modeling untested)
- `compute_training_recommendations()` — Workout suggestions (limiter prioritization untested)
- `compute_all()` — Main entry point (dataclass conversion untested)

**Why Critical:**
- Analytics drive all coaching decisions
- Wrong VDOT → wrong paces → athlete misguided
- CTL/ATL errors → overtraining risk not detected
- Predictions off by 5–10 min unnoticed

**Test File:** `tests/test_analytics_gaps.py` ✅ Provided
- VDOT estimation (recent vs stale, race vs easy runs)
- Race time forecasting (Riegel bounds, distribution)
- Load recovery (TSB risk thresholds, overtraining flag)
- Running economy (missing HR, edge cases)

---

### 3. Hyrox Scraper (35% | 262 stmts, 170 untested)

**Entry Point Status:** ❌ UNTESTED

**What's Missing:**
- `_parse_leaderboard()` — Table extraction (malformed HTML untested)
- `_extract_segment_times()` — Regex parsing (format variants untested)
- `_normalize_time_string()` — MM:SS vs H:MM:SS (edge cases untested)
- `scrape_leaderboard()` — Main API (pagination, 429 backoff untested)
- `scrape_segment_standards()` — Benchmark extraction (missing fields untested)
- `scrape_race_schedule()` — Race calendar (date format variants untested)
- `search_athlete_results()` — Athlete lookup (case sensitivity, dedup untested)
- `_geocode_hyrox()` — Location parsing (regex, city/date fallbacks untested)

**Why Critical:**
- Web scraping is fragile; HTML changes break parsing
- Silent failures (malformed HTML) → incomplete benchmarks
- Athlete searches return wrong data undetected
- No retry logic tested under network failures

**Test File:** `tests/test_hyrox_scraper_parsing.py` ✅ Provided
- Leaderboard parsing (complete, malformed, paginated)
- Time string normalization (MM:SS, HH:MM:SS, edge cases)
- Network errors (timeout, 429, 404)
- Segment extraction (missing fields, fallback paths)

---

### 4. Garmin Client (57% | 644 stmts, 280 untested)

**Entry Point Status:** ⚠️ PARTIAL

**What's Missing:**
- `_login_flow()` — OAuth2 + MFA (MFA prompt untested)
- `fetch_wellness()` — Daily stats (intermittent nulls untested)
- `fetch_activities()` — Activity list (empty list, rate-limit 429 untested)
- `fetch_activity_details()` — Splits + HR (404, parse error untested)
- `upload_structured_workout()` — Garmin steps (constraint validation untested)
- `delete_workout()` — Single/batch deletion (404 idempotency untested)
- `push_workout()` — Step conversions (step type mapping untested)
- `_parse_fit_file()` — FIT binary parsing (malformed file untested)

**Why Critical:**
- Garmin API failures cause sync loops to fail
- Malformed uploads corrupt Garmin calendar (undetected)
- Token refresh on 401 not tested → session expires, sync silent-fails
- Rate-limit backoff untested → rapid retries trigger 429 loops

**Test File:** `tests/test_garmin_client_auth.py` ✅ Provided
- OAuth2 + MFA flow (invalid creds, token refresh)
- Wellness fetch (complete, partial nulls, timeout, 401)
- Activity list (empty, paginated, 429 backoff)
- Workout upload (pace bounds, step conversion, permission denied 403)
- Workout deletion (success, 404 idempotency, batch)

---

## High-Priority Gaps (75-85% coverage)

### 5. Store I/O (75% | 207 stmts)

**Untested Functions:**
- `_write()` — Atomic file writes (temp file cleanup, os.replace never mocked)
- `save_profile()` — Merge logic (null preservation, field updates)
- `append_daily_history()` — JSONL upsert (merge, dedup, skip-all-null)
- `repair_history()` — Dedupe + schema migration
- `upsert_rpe()` — RPE indexing
- `load_token_meta()` / `save_token_meta()`
- `load_all_details()` — Detail file merge

**Why It Matters:** Atomic writes prevent corruption on crash; null merging preserves good data through Garmin outages.

**Test File:** `tests/test_store_file_io.py` ✅ Provided
- Atomic write (temp file, os.replace, cleanup on failure)
- Profile merge (null preservation, field replacement)
- Daily history (no date skip, all-null skip, merge, upsert)
- RPE storage (create, update)
- JSON parse errors (corrupt files)

---

### 6. Actions Business Logic (74% | 748 stmts)

**Untested End-to-End Flows:**
- `sync()` — Activity fetch + detail loop (N+1, rate-limit, retry untested)
- `brief()` — Daily briefing (HTML/Telegram formatting untested)
- `scaffold()` — Plan generation (goal→paces, volume untested)
- `push()` — Garmin upload (week selection, dry-run, constraint untested)
- `autosync()` — Plan reconciliation (delete stale, push 3 weeks untested)
- `recalibrate()` — Pace shifts (guard, future-week-only untested)
- `adapt()` — Missed-session reflow (readiness gate, scheduling untested)
- `plan_md()` — Plan document regeneration
- `validate()` — Plan validation wrapper

**Why It Matters:** These are production jobs; silent failures = missed sync cycles, wrong paces pushed, training derailed.

**Test File:** `tests/test_actions_integration.py` ✅ Provided
- Sync detail loop (limit, 404 skip, call count)
- Brief formatting (text, HTML, Telegram with escaping)
- Scaffold (goal→plan, target time adjustment)
- Recalibrate (delta direction, guard gating)
- Push (current+3-weeks, specific week, dry-run)
- Autosync (push, delete stale, reconcile)
- Adapt (reflow, readiness gate, downgrades)

---

## Implementation Priority

### Phase 1 (Critical Path — prevents data loss)

1. **test_store_file_io.py** — Atomic writes, null preservation
   - 6 tests, ~1 hour
   - Blocks: all data persistence
   
2. **test_cli_commands.py** — Command dispatch + output
   - 20 tests, ~2 hours
   - Blocks: all user interactions
   
3. **test_garmin_client_auth.py** — Auth + wellness fetch
   - 12 tests, ~2 hours
   - Blocks: sync loop reliability

### Phase 2 (High-Risk Business Logic)

4. **test_actions_integration.py** — Sync, push, adapt workflows
   - 15 tests, ~2.5 hours
   - Blocks: daily jobs, plan pushes
   
5. **test_analytics_gaps.py** — Compute functions (VDOT, CTL/ATL, predictions)
   - 18 tests, ~3 hours
   - Blocks: coaching recommendations accuracy

### Phase 3 (Robustness)

6. **test_hyrox_scraper_parsing.py** — Web parsing, fallbacks
   - 14 tests, ~2 hours
   - Reduces: benchmark data loss risk

---

## Test Skeleton Files Provided

| File | Tests | Coverage | Status |
|------|-------|----------|--------|
| `test_cli_commands.py` | 20 | cli.py: 0% → ~80% | ✅ Ready to run |
| `test_store_file_io.py` | 16 | store.py: 75% → ~95% | ✅ Ready to run |
| `test_garmin_client_auth.py` | 12 | garmin/client.py: 57% → ~75% | ✅ Ready to run |
| `test_actions_integration.py` | 15 | actions.py: 74% → ~85% | ✅ Ready to run |
| `test_analytics_gaps.py` | 18 | analytics.py: 18% → ~65% | ✅ Ready to run |
| `test_hyrox_scraper_parsing.py` | 14 | scraper.py: 35% → ~70% | ✅ Ready to run |

**Total:** 95 test skeletons, covering ~1200 previously-untested statements

---

## Untested Edge Cases & Error Paths

### Network Failures Never Tested
- `garmin.client`: 401 token refresh, 429 rate-limit backoff, timeouts
- `scraper.py`: HTTP timeouts, 404s, malformed responses
- `actions.py`: Garmin API unavailable, sync loop retry logic

### File I/O Not Tested
- `store.py`: Atomic write on crash, corrupt JSON, missing directories
- `actions.py`: Detail file saves, checkpoint recovery

### Error Handling Never Exercised
- `cli.py:178-180`: RuntimeError/KeyError exception handler
- `actions.py:368-383`: Readiness verdict None/edge cases
- `analytics.py`: Division by zero (zero time, zero distance)
- `planner.py`: Hyrox phase sequencing, goal feasibility checks

### Type Validation & Input Normalization Missing
- `store.py:172-181`: JSON parse errors, type mismatches
- `client.py:837-854`: Step type mapping completeness
- `scraper.py:67-87`: Time string format variants

### Boundary Conditions Untested
- Empty activity lists, zero-distance runs, null VDOT
- Single-workout plans, back-to-back hard sessions
- Very high/low TSB (-100/+100), zero pace (division error)

---

## Quick Start

**Run all new tests:**
```bash
python -m pytest tests/test_cli_commands.py tests/test_store_file_io.py \
  tests/test_garmin_client_auth.py tests/test_actions_integration.py \
  tests/test_analytics_gaps.py tests/test_hyrox_scraper_parsing.py -v
```

**Run with coverage:**
```bash
python -m pytest tests/test_*.py --cov=src/paceforge --cov-report=term-missing:skip-covered
```

**Target Coverage After Implementation:**
- cli.py: 0% → 80% (+132 stmts)
- analytics.py: 18% → 65% (+350 stmts)
- scraper.py: 35% → 70% (+115 stmts)
- garmin/client.py: 57% → 75% (+180 stmts)
- store.py: 75% → 95% (+45 stmts)
- actions.py: 74% → 85% (+80 stmts)

**Overall: 72% → ~82%** (estimated)

---

## Notes

- Test skeletons use `unittest.mock` + pytest; copy pattern to extend
- All network calls mocked; no live Garmin/web scraping in CI
- Fixtures and helpers available in existing test modules (reuse)
- Priority: run Phase 1 tests immediately (CLI, store, auth)
- Analytics tests need `compute_*` function outputs (use fixtures from existing tests as reference)

---

**For details on specific gaps, see:** `tasks/test-coverage-gaps-analysis.md`
