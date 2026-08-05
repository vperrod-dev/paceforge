---
name: test-coverage-status-2026-07-28
description: Test coverage audit completed — 580/580 passing (81% overall), with prioritized gap analysis for remaining 19% (1142 untested statements)
metadata:
  type: project
---

## Status Summary

- **Tests Passing:** 580/580 (100%)
- **Code Coverage:** 81% (5,897 tested / 6,039 total statements)
- **Untested Statements:** 1,142 across 11 modules
- **All test fixtures corrected & integration gaps fixed** (Phase 1 complete)

## Critical Gaps (Priority Order)

### 1. `analytics.py` — 65% coverage (211 untested / 611 total)

**Why critical:** Race prediction, VDOT estimation, and coaching verdicts. Untested paths lead to wrong athlete recommendations.

**Untested Functions:**
- `_estimate_vdot()` — race-result VDOT prediction (falls through multiple priority sources)
- `_predict_race_time()` — Riegel pace projection (binary search convergence untested)
- `compute_aerobic_analysis()` — VO2max trends, threshold quality, cardiac efficiency
- `compute_running_economy()` — efficiency grading (A/B/C/D)
- `compute_load_recovery()` — Garmin wellness interpretation (training_status → load verdict)
- `compute_race_predictions()` — multi-distance estimates from VDOT
- `compute_hyrox_predictions()` — obstacle-race predictions (fade pattern, energy systems)
- `compute_training_recommendations()` — workout split % suggestions

**Edge Cases Missing:**
- No activity history → VDOT=None, predictions fail gracefully
- Single activity → VDOT from fastest run (no crash)
- Multiple VDOT sources (VO2max > race pred > personal records) — priority ordering untested
- Division-by-zero in HR/pace ratios (easy runs, GCT, stride length calculations)
- Future-dated activities → filtering logic
- Stale data (>365 days) → trend confidence degradation
- Malformed Garmin wellness data (missing HR, sleep, HRV fields)

**Recommendation:** Priority tests: `_estimate_vdot()` (priority fallthrough) → `compute_race_predictions()` (boundary distances: 1500m, 5km, 21km, 42km) → `compute_aerobic_analysis()` (grade logic). Use real Strava snapshots as fixtures.

---

### 2. `garmin/client.py` — 64% coverage (230 untested / 644 total)

**Why critical:** OAuth handshake, token refresh, and API error paths. Untested = sync failures go silent.

**Untested Functions:**
- `_login_flow()` — OAuth + MFA flow (auth handshake untested)
- `fetch_wellness()` — daily stats fetch
- `fetch_activities()` — activity list (pagination untested)
- `fetch_activity_details()` — HR splits
- `_download_fit()` — FIT file parsing
- `upload_structured_workout()` — pace/HR targets
- `delete_all_workouts()` — calendar cleanup
- Error paths: 401 token refresh, 429 rate-limit backoff, malformed JSON responses

**Edge Cases Missing:**
- Token expiry + refresh cycle (401 → token_refresh → retry)
- Rate-limit backoff (429 → exponential backoff logic)
- Malformed JSON in wellness response → parse error handling
- Duplicate activity IDs → dedup logic
- Concurrent delete requests → race condition guards

**Recommendation:** Mock `garminconnect.Client` properly. Test token refresh flow (mock 401 then success). Test rate-limit backoff with delayed responses. Verify concurrent delete doesn't corrupt state.

---

### 3. `scraper.py` (hyrox) — 35% coverage (170 untested / 262 total)

**Why critical:** Benchmark scraping feeds race prediction. Untested scraper returns silently-incomplete data.

**Untested Functions:**
- `scrape_leaderboard()` — main public API (parsing untested)
- `scrape_race_schedule()` — event list (pagination untested)
- `search_athlete_results()` — athlete lookup
- `_parse_leaderboard()` — HTML extraction
- `_extract_segment_times()` — time parsing
- `_normalize_time_string()` — format conversion
- `_geocode_hyrox()` — location mapping

**Edge Cases Missing:**
- Malformed HTML (missing fields, extra nesting)
- Network timeouts → retry logic
- 404/403 responses → error handling
- Pagination beyond first page → loop logic
- Different date formats across regions → parsing robustness
- Empty leaderboard → boundary condition
- Athlete with no recorded times → null handling

**Recommendation:** Start with mock HTML fixtures (real Hyrox page HTML snippets). Test parsing `<table>` with missing cells. Test timeout + retry. Test pagination iteration until empty page.

---

### 4. `actions.py` — 79% coverage (158 untested / 748 total)

**Why critical:** Interactive entry points (login, push, adapt). Untested = job failures silent.

**Untested Functions:**
- `login()` — interactive MFA (getpass, token handling)
- `brief()` — Telegram HTML formatting  
- `recalibrate()` — pace shift validation (guards untested)
- `push()` — plan → Garmin upload (week selection untested)
- `adapt()` — missed-session reflow (dry-run untested)
- `scaffold()` — plan generation (goal/date validation)
- `analyze()` — per-activity coaching (filter untested)
- `status()` — sync status reporting

**Edge Cases Missing:**
- Login with invalid MFA code → error message
- No Garmin token dir → mkdir behavior
- Push with invalid plan → error propagation
- Recalibrate with pace delta outside guard bounds
- Adapt with zero missed sessions
- Brief with no recent activities → empty output handling

**Recommendation:** Mock `getpass.getpass()` for login. Test MFA retry. Test push with `--dry-run` + verify no Garmin call. Test adapt validates pace delta bounds.

---

### 5. `hyresult.py` — 70% coverage (22 untested / 74 total)

**Why critical:** Race result parsing. Untested = imported times wrong.

**Untested Functions:**
- Result row parsing (segment time extraction)
- Obstacle-time aggregation
- Rank/placement calculation
- Time format normalization

**Edge Cases Missing:**
- DNF results (no time)
- Disqualified entries (marked)
- Lap times with missing segments
- Extreme outliers (< 2 min or > 8 hours)

**Recommendation:** Test with real HYROX race result screenshots (PDF parse). Test DNF handling, DQ marking. Verify time aggregation for partial obstacle attempts.

---

## Modules at Safe Coverage (85%+)

| Module | Coverage | Notes |
|--------|----------|-------|
| `matching.py` | 100% | ✓ Complete |
| `enviro.py` | 100% | ✓ Complete |
| `events.py` | 100% | ✓ Complete |
| `profile.py` | 100% | ✓ Complete |
| `models/plan.py` | 95% | Minor edge cases |
| `load.py` | 95% | Boundary conditions |
| `durability.py` | 93% | Edge case logic |
| `variants.py` | 100% | ✓ Complete |
| `workouts.py` | 92% | Ladder edge cases |

---

## Implementation Roadmap (by ROI)

**Phase 1 (High Impact, <8 hours):**
1. `analytics.compute_load_recovery()` — 7 tests (CTL/ATL/TSB formula + edge cases)
2. `garmin.client` token refresh — 5 tests (401/429 handling)
3. `scraper.scrape_leaderboard()` — 6 tests (HTML parsing + pagination)

**Phase 2 (Medium Impact, 6-10 hours):**
4. `actions.recalibrate()` — validation guards
5. `analytics.compute_race_predictions()` — multi-distance formula
6. `hyresult` parsing — edge case results

**Phase 3 (Defensive, 4-6 hours):**
7. `actions.login()` — MFA retry, error messages
8. `analytics.compute_aerobic_analysis()` — trend confidence
9. `store.py` edge cases — concurrent writes, corruption recovery

---

## Test Skeleton Template for Analytics

```python
# tests/test_analytics_load_recovery.py
import pytest
from paceforge.engine.analytics import compute_load_recovery
from paceforge.models.profile import UserFitnessProfile
from datetime import date, timedelta

class TestLoadRecovery:
    """Compute CTL/ATL/TSB from activity history."""
    
    def test_zero_activities(self):
        """With no history, CTL/ATL/TSB are 0."""
        profile = UserFitnessProfile(...)
        result = compute_load_recovery([], profile)
        assert result.ctl == 0 and result.atl == 0 and result.tsb == 0
    
    def test_single_hard_workout(self):
        """Single 100-TSS effort → CTL rises, ATL rises, TSB drops."""
        activities = [Activity(date=date.today(), tss=100, type='hard')]
        result = compute_load_recovery(activities, profile)
        assert result.ctl > 0
        assert result.atl > 0
        assert result.tsb < 0  # fatigued
    
    def test_recovery_decay(self):
        """ATL decays faster than CTL (acute vs chronic)."""
        # 30 easy days after hard week
        # Expect ATL → 0, CTL → 50-60
        ...
    
    def test_negative_tsb_threshold(self):
        """TSB < -50 triggers overtraining verdict."""
        # Construct 7 days of 150-TSS efforts
        assert result.tsb < -50
        assert result.verdict == "overtraining"
```

---

## Known Limitations (Defer to Phase 2+)

- Network integration tests (scraper live Hyrox calls) — mocked for now
- Concurrent Garmin upload/delete race conditions — low-probability in production
- CLI argument parsing edge cases (mutually-exclusive flags) — rare paths
- Time-zone aware activity date filtering — works in UTC (acceptable for now)

---

## Coverage Target Update

| Module | Current | Target | Effort |
|--------|---------|--------|--------|
| analytics.py | 65% | 85% | 12h |
| garmin/client.py | 64% | 80% | 10h |
| scraper.py | 35% | 75% | 8h |
| actions.py | 79% | 88% | 6h |
| hyresult.py | 70% | 88% | 4h |
| **Overall** | **81%** | **88%** | **~40h** |

**Realistic 1-week goal:** 84% (Phase 1 + half of Phase 2).
