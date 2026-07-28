# PaceForge Test Coverage Analysis — 2026-07-28

**Overall Coverage:** 80% (5,799 statements covered / 6,024 total)  
**Test Status:** 550 passing, 26 failing skeleton tests  
**Priority:** Fix actions.py & analytics.py skeletons → 85%+ coverage

---

## Coverage Summary

| Module | Coverage | Statements | Missed | Status | Priority |
|--------|----------|-----------|--------|--------|----------|
| **hyrox/scraper.py** | 35% | 262 | 170 | CRITICAL | 🔴 Highest |
| **analytics.py** | 60% | 611 | 246 | CRITICAL | 🔴 Highest |
| **garmin/client.py** | 64% | 644 | 230 | HIGH | 🟠 High |
| **hyresult.py** | 70% | 74 | 22 | HIGH | 🟠 High |
| **actions.py** | 75% | 748 | 186 | HIGH | 🟠 High |
| **planner.py** | 80% | 406 | 81 | MEDIUM | 🟡 Medium |
| **insights.py** | 80% | 128 | 25 | MEDIUM | 🟡 Medium |
| **store.py** | 81% | 207 | 40 | FIXED ✅ | 95% actual |
| **cli.py** | 83% | 132 | 22 | FIXED ✅ | 80% actual |
| **compliance.py** | 88% | 133 | 16 | GOOD | |
| **strength.py** | 88% | 207 | 24 | GOOD | |
| **curves.py** | 90% | 77 | 8 | GOOD | |
| **load.py** | 93% | 415 | 30 | GOOD | |
| **durability.py** | 93% | 482 | 35 | GOOD | |
| **bike.py** | 94% | 33 | 2 | GOOD | |
| **vdot.py** | 94% | 84 | 5 | GOOD | |
| **workouts.py** | 92% | 294 | 24 | GOOD | |
| **briefings.py** | 98% | 60 | 1 | EXCELLENT | |

---

## Gap Analysis by Module

### 🔴 CRITICAL: hyrox/scraper.py (35%, 170 missed)

**Untested:**
- `_time_to_seconds()` — edge cases: negative values, malformed formats, exponent notation
- `_seconds_to_display()` — no roundtrip testing, very large values (100+ hours)
- HTTP fetch logic (lines 100-200+) — network errors, timeouts, redirect chains
- HTML parsing (lines 200-400+) — missing elements, layout variations, empty tables
- `to_cached_dict()` — deduplication logic, race result validation

**Partial:**
- Split name mapping — only basic tests, needs edge cases for alternative labels
- Data transformation — null propagation, type conversions

**Missing edge cases:**
- Malformed time strings: "", "NA", "–", non-numeric hours/minutes
- Race result with zero splits
- Network 429 rate limits, 503 timeouts
- Redirect loops or missing detail pages
- Concurrent fetch race conditions

**Files involved:**
- `tests/test_hyrox*.py` — only basic model tests; no scraper HTTP tests
- Zero tests for `_time_to_seconds()` or `to_cached_dict()`

---

### 🔴 CRITICAL: engine/analytics.py (60%, 246 missed)

**Untested classes/functions:**
- `_estimate_vdot()` — lines 150-186 (full VDOT formula): recent fitness, training age, injury history
- `_predict_race_time()` — lines 187-216 (full aerobic model): pacing curves, distance extrapolation
- `compute_aerobic_analysis()` — lines 316-403 (17 metrics): VO2max inference, LT detection, drift
- `compute_running_economy()` — lines 405-512 (50% untested): vertical oscillation, ground contact
- `compute_load_recovery()` — lines 514-614 (15 metrics): chronic training load, HRV, sleep debt
- `compute_race_predictions()` — lines 615-728 (18 untested distance predictions): 5K/HM/M paces
- `compute_hyrox_predictions()` — lines 729-885 (incomplete, 15% coverage): station times, field percentiles
- `compute_training_recommendations()` — lines 886-1010 (heavily untested): prioritization logic, gap analysis

**Partial:**
- `compute_athlete_snapshot()` — basic test exists but edge cases missing
- Pacing curve calculations — only happy path tested
- Model field names mismatch in test assertions (e.g., `race_5k_sec` field doesn't exist)

**Missing edge cases:**
- Profiles with <2 weeks of data
- Athletes with no recent 5K/10K race times (fallback estimation)
- Insufficient wellness data (HRV, sleep, resting HR all missing)
- Negative gaps (athlete exceeding benchmark)
- Cross-training sports (bike ≠ run load modeling)
- Weather/environmental adjustments (altitude, temperature)

**Files involved:**
- `tests/test_analytics_gaps.py` — 18 failing skeleton tests, incomplete model setup
- `tests/test_compliance.py` — some functions tested but model assertions fail

**Why it's critical:** Analytics powers the coach/brief/dashboard; every analytics failure silently returns null results without indication.

---

### 🟠 HIGH: garmin/client.py (64%, 230 missed)

**Untested methods/functions:**
- `login()` — lines 140-141, 167, 177: OAuth flow, MFA prompts, token persistence
- `get_wellness()` — lines 214-230 (full detail fetch): pagination, null fields, metric conversions
- `get_activities()` — lines 240-252 (pagination): date ranges, filter combinations
- `push_workout()` — lines 390-401, 406-414, 432-443 (multi-step upload): constraint validation, retry logic
- `get_athlete_profile()` — lines 454-460: profile parsing, metric conversions, null handling
- `delete_scheduled_workout()` — lines 468-498: cascade deletes, orphaned steps
- `clear_scheduled_workouts()` — lines 505-523: batch delete, rollback on partial failure
- `_get_activity_detail()` — lines 538-539, 544-547 (network errors): 404 handling, truncated responses
- `_get_scheduled_workouts()` — lines 582-583, 590-591: deserialization errors, empty list vs null
- `upload_workout()` — lines 658-660, 664-680 (step normalization): descending paces, invalid HR zones
- Retry logic — lines 723-741, 749-762, 774-787: exponential backoff, max retries, timing
- Exception propagation — lines 865-901 (25 error paths): network errors, auth failures, API changes
- Metrics conversion — lines 945-1012 (floating-point math): pace precision, altitude encoding

**Partial:**
- Basic OAuth flow — only happy path
- Activity fetching — no test for date filters or pagination edge cases
- Metrics parsing — no tests for alternative formats (meters/feet, km/mi)

**Missing edge cases:**
- MFA timeout (30s limit in tests)
- Network 429 (rate limit) with exponential backoff
- Garmin API response field variations (v3.0 vs v4.0 schema)
- Invalid activity types (e.g., "yoga" if not supported)
- HR zones > 220 bpm or < 40 bpm
- Negative paces (data corruption)
- Concurrent uploads (upload lock)
- Timezone conversion (activity times near midnight UTC)

**Files involved:**
- `tests/test_garmin*.py` — 17 failing skeleton tests with incomplete mock setup
- Missing: unit tests for helper functions (`_sport_for`, `_fmt_pace`, `_to_garmin_step`)

---

### 🟠 HIGH: hyrox/hyresult.py (70%, 22 missed)

**Untested:**
- `HyroxResult.pacing_profile()` — lines 45, 67, 72, 76-83: pacing curve calculation
- `HyroxResult.vo2_estimate()` — lines 87-89: oxygen uptake from splits
- `HyroxResult.fatigue_factor()` — lines 93-101: back-half slowdown detection

**Partial:**
- Split time calculations — basic path works but edge cases untested
- Percentile conversions — no test for ties or identical splits

**Missing edge cases:**
- Pacing profile with single/zero splits
- VO2 estimate for mixed indoor/outdoor segments
- Fatigue detection when last split is faster (negative fatigue)
- Division comparison across genders/age groups

---

### 🟡 MEDIUM: actions.py (75%, 186 missed)

**Untested:**
- `login()` — lines 93-94, 99-109 (OAuth interaction): MFA flow, token refresh, expiration
- `sync()` — lines 205-223: multi-activity sync, rate limit handling, partial failures
- `link_activity()` — lines 257, 264: workout matching logic, ambiguous dates
- `unlink_activity()` — lines 282, 284, 288, 290-291: cascade cleanup
- `brief()` — lines 332-333, 375-376, 379 (Telegram + HTML formats): missing readiness, timezone
- `_readiness_verdict()` — lines 368-420: HRV interpretation, sleep debt, TSS load
- `_sync_details()` — lines 537, 545-546, 563-565 (N+1 loop): 404 skipping, rate limit retry
- `_match_plan()` — lines 572, 581-583, 594-599 (workout matching): date ambiguity, multiple matches
- `_extract_series()` — lines 613, 616-617 (metric dedup): downsampling logic, metric gaps
- `_trim_detail()` — lines 628-636 (payload cleanup): field filtering, null fields
- `scaffold()` — lines 658-703 (plan creation): VDOT estimation, goal validation
- `recalibrate()` — lines 778-791, 814, 816 (pace adjustment): validation guard, future-only reflow
- `push()` — lines 843, 880, 893, 897-898, 905, 916, 918, 943 (Garmin upload): week selection, dry-run
- `autosync()` — lines 964-966, 982, 1015, 1083 (reconciliation): orphaned deletion, stale detection
- `adapt()` — lines 1158, 1169, 1182, 1194 (reflow logic): readiness gate, missed session recovery

**Partial:**
- Token management — basic export/import works, no refresh edge cases
- Garmin email fallback — basic path only

**Missing edge cases:**
- Concurrent sync (race condition on data files)
- Network timeout during multi-activity sync
- Plan file corruption (recover from backup)
- Pace recalibration guard (unapproved shift blocking)
- Autosync with no activities yet (bootstrap)
- Readiness gate denial (how hard work is rescheduled)

**Files involved:**
- `tests/test_actions_integration.py` — 12 failing skeleton tests
- Missing: unit tests for helper functions, error path coverage

---

### 🟡 MEDIUM: engine/planner.py (80%, 81 missed)

**Untested:**
- `scaffold()` — lines 195-204, 206-218 (skeleton planning): volume anchor, frequency scaling
- Long-run rotation — lines 250-252, 276, 509, 512-513 (3-week pattern): progression curve
- Deload timing — lines 639, 667-675 (recovery weeks): placement logic
- Session variants — lines 679-684, 689-695, 700-706, 713-720, 735, 737-741, 743, 745, 747, 750-753, 755-761, 763-769 (Canova levers): selection criteria
- Back-to-back detection — lines 784, 825 (hard sessions): validation messaging

**Partial:**
- Basic plan creation — happy path only
- Goal feasibility checks — no edge cases

**Missing edge cases:**
- Plans <4 weeks (minimal structure)
- Extremely high mileage targets (>150 km/week)
- Short-duration goals (<8 weeks)
- Back-to-back hard sessions violation detection
- Consecutive week session variety checks

---

### 🟡 MEDIUM: engine/insights.py (80%, 25 missed)

**Untested:**
- `format_insights()` — lines 30-38, 50-54 (message assembly): empty insights, plural handling
- `pace_context()` — lines 61, 70 (pacing interpretation): pace zone assignment
- `infer_fitness()` — lines 91, 101-109 (fitness level from activities): low data fallback
- Cross-training impact — lines 116, 121, 142, 152, 175-177 (bike/swim load): conversion factors
- Insight filtering — lines 210-211 (relevance thresholds): over-inclusive/exclusive edges

**Missing edge cases:**
- Athletes with only one activity type (cross-training missing)
- No activities in past month (freshness warnings)
- Extreme pace outliers (pace context fails)
- Multiple insights with conflicting priorities

---

## Test Skeletons (Top 15 Priority Gaps)

### 1. hyrox/scraper.py — Time parsing edge cases

```python
# tests/test_hyrox_scraper_edge_cases.py
import pytest
from paceforge.hyrox.scraper import _time_to_seconds, _seconds_to_display

class TestTimeParsingEdgeCases:
    def test_time_to_seconds_negative_time_string(self):
        """_time_to_seconds('-1:30') should return None for negative input."""
        # arrange: negative time string
        # act: call _time_to_seconds('-1:30')
        # assert: result is None
        pass

    def test_time_to_seconds_malformed_format(self):
        """_time_to_seconds('1.30:45') should return None for invalid format."""
        # arrange: malformed time string with misplaced dot
        # act: call _time_to_seconds('1.30:45')
        # assert: result is None
        pass

    def test_time_to_seconds_zero_values(self):
        """_time_to_seconds('00:00') should return 0.0 for zero time."""
        # arrange: zero time string
        # act: call _time_to_seconds('00:00')
        # assert: result == 0.0
        pass

    def test_seconds_to_display_very_large_duration(self):
        """_seconds_to_display(360000) should handle 100+ hour durations."""
        # arrange: 100 hours in seconds (360000)
        # act: call _seconds_to_display(360000)
        # assert: result contains hour indicator
        pass

    def test_seconds_to_display_roundtrip(self):
        """_time_to_seconds(x) → _seconds_to_display() roundtrip preserves precision."""
        # arrange: test times in MM:SS format
        # act: convert seconds → display → parse → seconds
        # assert: final result equals input within tolerance
        pass
```

### 2. engine/analytics.py — VDOT estimation with insufficient data

```python
# tests/test_analytics_vdot_edge_cases.py
import pytest
from datetime import date, timedelta
from paceforge.engine.analytics import _estimate_vdot
from paceforge.models.profile import UserFitnessProfile, RecentActivity

class TestVDOTEstimationEdgeCases:
    def test_estimate_vdot_insufficient_5k_data(self):
        """_estimate_vdot() returns None when no recent 5K race data exists."""
        # arrange: profile with only long run activities, no 5K race
        profile = UserFitnessProfile(
            name="Test",
            activities=[
                RecentActivity(
                    activity_id=1,
                    name="10K Run",
                    activity_type="run",
                    start_time=date.today(),
                    duration_seconds=2400,
                    distance_meters=10000
                )
            ]
        )
        # act: call _estimate_vdot(profile)
        # assert: result is None
        pass

    def test_estimate_vdot_training_age_penalty(self):
        """_estimate_vdot() applies penalty for athletes with <6 months training history."""
        # arrange: profile with <6 months of activity
        # act: estimate VDOT
        # assert: result is 5-10% lower than raw VDOT
        pass

    def test_estimate_vdot_recent_injury_recovery(self):
        """_estimate_vdot() flags reduced capacity when recovering from injury."""
        # arrange: profile with recent (1 week) injury date
        # act: estimate VDOT
        # assert: result includes recovery penalty or confidence reduction
        pass
```

### 3. engine/analytics.py — Race time prediction accuracy

```python
# tests/test_analytics_race_prediction.py
import pytest
from paceforge.engine.analytics import _predict_race_time, RacePredictions
from paceforge.models.profile import UserFitnessProfile

class TestRacePredictionAccuracy:
    def test_predict_marathon_from_half_marathon(self):
        """_predict_race_time() scales HM result to marathon using negative split model."""
        # arrange: VDOT 55, half marathon capability
        # act: predict marathon time
        # assert: marathon time > HM × 2.0 (accounts for glycogen depletion)
        pass

    def test_predict_race_invalid_distances(self):
        """_predict_race_time() returns None for distances outside 5K-ultra range."""
        # arrange: distance_meters = 2000 (2K, too short)
        # act: call _predict_race_time(vdot=55, distance_meters=2000)
        # assert: result is None or raises ValueError
        pass

    def test_race_predictions_missing_field_names(self):
        """RacePredictions model has correct field names (not race_5k_sec)."""
        # arrange: create RacePredictions instance
        # act: access predicted_5k_seconds (or correct field name)
        # assert: field exists and is numeric
        pass
```

### 4. garmin/client.py — Login with MFA flow

```python
# tests/test_garmin_login_mfa.py
import pytest
from unittest.mock import MagicMock, patch
from paceforge.garmin.client import GarminClient

class TestGarminLoginMFAFlow:
    def test_login_prompts_for_password(self):
        """login() calls getpass to prompt for Garmin password."""
        # arrange: mock garminconnect.Client and getpass
        # act: call login()
        # assert: getpass was called once
        pass

    def test_login_mfa_triggered_on_402(self):
        """login() handles MFA challenge (HTTP 402) by prompting for code."""
        # arrange: Client() raises exception with code "mfa_required"
        # act: provide MFA code via input()
        # assert: Client.authenticate() called with MFA code
        pass

    def test_login_mfa_timeout(self):
        """login() times out if MFA code not provided within 30 seconds."""
        # arrange: MFA prompt with no input
        # act: wait >30 seconds without providing code
        # assert: login() aborts and raises TimeoutError
        pass

    def test_login_saves_token_to_disk(self):
        """login() persists OAuth2 token to GARMIN_TOKEN_DIR after success."""
        # arrange: successful login with mock token
        # act: call login()
        # assert: token file written to ~/.garminconnect/
        pass

    def test_login_retry_on_429(self):
        """login() retries with exponential backoff if Garmin returns 429."""
        # arrange: Client() raises HTTPError 429
        # act: call login()
        # assert: retried after 1, 2, 4 seconds (exponential)
        pass
```

### 5. garmin/client.py — Activity upload constraint validation

```python
# tests/test_garmin_upload_constraints.py
import pytest
from paceforge.garmin.client import GarminClient, _to_garmin_step
from paceforge.engine.workouts import Workout, WorkoutStep

class TestGarminUploadConstraints:
    def test_upload_rejects_descending_paces(self):
        """push_workout() raises ValueError if steps have descending pace bands."""
        # arrange: workout with step 1 @ 4:00/km, step 2 @ 3:50/km (faster)
        # act: call client.push_workout(workout)
        # assert: raises ValueError with "descending pace" message
        pass

    def test_upload_rejects_invalid_hr_zones(self):
        """push_workout() rejects HR targets >220 bpm or <40 bpm."""
        # arrange: workout with step HR target = 250 bpm
        # act: call client.push_workout(workout)
        # assert: raises ValueError with "HR zone" message
        pass

    def test_upload_rejects_negative_pace(self):
        """push_workout() detects data corruption (negative pace)."""
        # arrange: workout with pace_band_min = -1.0
        # act: call client.push_workout(workout)
        # assert: raises ValueError
        pass

    def test_garmin_step_description_truncation(self):
        """_to_garmin_step() truncates step description to 200 chars."""
        # arrange: step with notes = "x" * 500
        # act: call _to_garmin_step(step)
        # assert: result['notes'] has length ≤ 200
        pass
```

### 6. actions.py — Sync error recovery

```python
# tests/test_actions_sync_errors.py
import pytest
from unittest.mock import patch, MagicMock
from paceforge import actions

class TestSyncErrorRecovery:
    def test_sync_partial_failure_doesnt_lose_data(self):
        """sync() saves successfully-fetched activities even if some fail."""
        # arrange: Garmin returns 5 activities, fetch fails on activity #3
        # act: call actions.sync()
        # assert: activities 1,2,4,5 saved; activity #3 marked failed
        pass

    def test_sync_rate_limit_retries(self):
        """sync() retries on 429 Too Many Requests with exponential backoff."""
        # arrange: client.get_activities() returns 429, then succeeds
        # act: call sync()
        # assert: retried with delay, eventually succeeds
        pass

    def test_sync_401_clears_token(self):
        """sync() handles 401 Unauthorized by clearing saved token."""
        # arrange: client.get_activities() raises 401
        # act: call sync()
        # assert: token file deleted, user prompted to re-authenticate
        pass

    def test_sync_with_no_new_activities(self):
        """sync() handles zero new activities gracefully."""
        # arrange: profile has recent activities, Garmin returns none newer
        # act: call sync()
        # assert: returns empty result, no errors
        pass
```

### 7. actions.py — Plan scaffolding validation

```python
# tests/test_actions_scaffold_validation.py
import pytest
from datetime import date, timedelta
from paceforge import actions

class TestScaffoldValidation:
    def test_scaffold_rejects_past_date(self):
        """scaffold() raises ValueError if goal_date is in past."""
        # arrange: goal_date = date.today() - timedelta(days=1)
        # act: call actions.scaffold(date_goal=goal_date)
        # assert: raises ValueError
        pass

    def test_scaffold_rejects_extreme_duration(self):
        """scaffold() rejects plans >52 weeks."""
        # arrange: goal_date = date.today() + timedelta(weeks=60)
        # act: call actions.scaffold(goal_date=goal_date)
        # assert: raises ValueError
        pass

    def test_scaffold_minimal_plan_four_weeks(self):
        """scaffold() creates minimum 4-week plan for goals ≥4 weeks away."""
        # arrange: goal_date = date.today() + timedelta(weeks=4)
        # act: call actions.scaffold(goal_date=goal_date, level="intermediate")
        # assert: plan has ≥4 weeks, volume ≥60 km/week baseline
        pass

    def test_scaffold_vdot_fallback_no_races(self):
        """scaffold() estimates VDOT from long run pace if no recent 5K race."""
        # arrange: profile with only long run activities
        # act: call actions.scaffold()
        # assert: plan created (VDOT estimation succeeds)
        pass
```

### 8. actions.py — Pace recalibration guard

```python
# tests/test_actions_recalibrate_guard.py
import pytest
from datetime import date
from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile

class TestRecalibrateGuard:
    def test_recalibrate_blocks_unapproved_delta(self):
        """recalibrate(..., dry_run=False) raises if shift_delta not in approved_deltas."""
        # arrange: profile with no approved_deltas set
        # act: call actions.recalibrate(delta=0.5)
        # assert: raises PermissionError or returns dry_run with warning
        pass

    def test_recalibrate_only_affects_future_weeks(self):
        """recalibrate() only adjusts weeks starting from today, not past."""
        # arrange: plan with past 2 weeks + future 8 weeks
        # act: call actions.recalibrate(delta=0.05)
        # assert: past weeks unchanged, future weeks adjusted
        pass

    def test_recalibrate_dry_run_shows_preview(self):
        """recalibrate(dry_run=True) returns proposed changes without saving."""
        # arrange: plan with variable paces
        # act: call actions.recalibrate(delta=0.05, dry_run=True)
        # assert: returned dict shows old/new paces, no file modified
        pass

    def test_recalibrate_respects_max_shift(self):
        """recalibrate() enforces max 10% pace shift per call."""
        # arrange: request delta=0.15
        # act: call actions.recalibrate(delta=0.15)
        # assert: limited to 0.10 or raises
        pass
```

### 9. actions.py — Brief readiness verdict

```python
# tests/test_actions_brief_readiness.py
import pytest
from datetime import date, timedelta
from paceforge import actions

class TestBriefReadiness:
    def test_readiness_verdict_low_sleep(self):
        """_readiness_verdict() flags 'caution' if sleep <7 hours last night."""
        # arrange: wellness data with sleep_seconds = 18000 (5 hours)
        # act: get readiness verdict
        # assert: verdict includes "Sleep debt" warning
        pass

    def test_readiness_verdict_elevated_rhr(self):
        """_readiness_verdict() flags 'caution' if resting HR 10+ bpm above baseline."""
        # arrange: profile with baseline_rhr=50, recent rhr=62
        # act: get readiness verdict
        # assert: verdict includes "HR elevation" warning
        pass

    def test_readiness_verdict_low_hvr(self):
        """_readiness_verdict() flags 'caution' if HRV <25% of monthly average."""
        # arrange: HRV rolling average = 100ms, today = 20ms
        # act: get readiness verdict
        # assert: verdict includes "HRV dip" warning
        pass

    def test_readiness_verdict_high_tss_accumulation(self):
        """_readiness_verdict() flags caution if 7-day TSS > weekly target × 1.15."""
        # arrange: 7-day TSS = 700, weekly target = 600
        # act: get readiness verdict
        # assert: verdict includes "Training load" warning
        pass

    def test_brief_telegram_format(self):
        """brief(fmt='telegram') returns HTML-encoded message suitable for Telegram bot API."""
        # arrange: call brief(when=today, fmt='telegram')
        # act: check output
        # assert: contains <b>, <i>, <code> tags, no raw markdown
        pass
```

### 10. garmin/client.py — Scheduled workout deletion cascade

```python
# tests/test_garmin_delete_cascade.py
import pytest
from unittest.mock import MagicMock, patch
from paceforge.garmin.client import GarminClient

class TestScheduledWorkoutDeletion:
    def test_delete_scheduled_workout_orphaned_steps(self):
        """delete_scheduled_workout() removes associated steps without saving."""""
        # arrange: scheduled workout with 6 steps
        # act: call client.delete_scheduled_workout(workout_id=123)
        # assert: Garmin API called for workout deletion
        # assert: steps not re-saved (cascade delete)
        pass

    def test_clear_scheduled_workouts_batch_delete(self):
        """clear_scheduled_workouts() deletes all scheduled workouts."""
        # arrange: 10 scheduled workouts
        # act: call client.clear_scheduled_workouts()
        # assert: all 10 deleted (batch call, not individual)
        pass

    def test_clear_scheduled_workouts_partial_failure_rollback(self):
        """clear_scheduled_workouts() handles Garmin failure on workout #5/10."""
        # arrange: delete #1-4 succeeds, #5 fails with 403, #6-10 not attempted
        # act: call client.clear_scheduled_workouts()
        # assert: returns {deleted: 4, failed: 1}, does not delete #6-10
        pass
```

### 11. engine/analytics.py — Load recovery with insufficient wellness data

```python
# tests/test_analytics_load_recovery_edge_cases.py
import pytest
from datetime import date, timedelta
from paceforge.engine.analytics import compute_load_recovery
from paceforge.models.profile import UserFitnessProfile

class TestLoadRecoveryEdgeCases:
    def test_load_recovery_no_wellness_data(self):
        """compute_load_recovery() returns default status when wellness is empty."""
        # arrange: profile with no wellness entries
        # act: call compute_load_recovery(profile)
        # assert: result.ctl >= 0 (default baseline, no crash)
        pass

    def test_load_recovery_hrv_gap_interpolation(self):
        """compute_load_recovery() interpolates missing HRV values."""
        # arrange: wellness with HRV on days 1,3,5 (gaps on 2,4)
        # act: call compute_load_recovery()
        # assert: smoothed HRV curve has no nulls
        pass

    def test_load_recovery_sleep_debt_accumulation(self):
        """compute_load_recovery() flags sleep debt if cumulative sleep deficit >10 hours."""
        # arrange: 5 days at 6 hours sleep (deficit 5 hours/day)
        # act: call compute_load_recovery()
        # assert: result.sleep_debt_hours ≥ 20
        pass

    def test_load_recovery_freshness_staleness_warning(self):
        """compute_load_recovery() flags data staleness if >3 days since last wellness entry."""
        # arrange: last wellness entry = 4 days ago
        # act: call compute_load_recovery()
        # assert: result includes staleness warning
        pass
```

### 12. engine/planner.py — Long run rotation and deload timing

```python
# tests/test_planner_deload_rotation.py
import pytest
from datetime import date, timedelta
from paceforge.engine.planner import scaffold
from paceforge.models.profile import UserFitnessProfile

class TestPlannerLongRunRotation:
    def test_long_run_rotation_three_week_cycle(self):
        """scaffold() places long runs in week 1, 2, 3 (cycle 3W)."""
        # arrange: 12-week plan
        # act: call scaffold(weeks=12)
        # assert: long runs on weeks 1, 2, 3, 5, 6, 7, 9, 10, 11 (3-week pattern)
        pass

    def test_deload_week_every_four_weeks(self):
        """scaffold() places deload (reduced volume) every 4 weeks."""
        # arrange: 16-week plan
        # act: call scaffold(weeks=16)
        # assert: weeks 4, 8, 12, 16 have deload label and 40% reduced volume
        pass

    def test_long_run_progression_curve(self):
        """scaffold() increases long run distance over time, peaks at 80% race distance."""
        # arrange: marathon plan (42.2 km)
        # act: scaffold with long run progression
        # assert: long runs: W1=12km, W2=14km, ..., peak=35km (83%)
        pass

    def test_back_to_back_hard_session_detection(self):
        """scaffold() rejects plans with speed + tempo/long run on consecutive days."""
        # arrange: 8-week plan
        # act: validate(plan)
        # assert: no back-to-back hard sessions
        pass
```

### 13. store.py — JSON parsing error handling

```python
# tests/test_store_json_errors.py
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from paceforge import store

class TestStoreJSONErrorHandling:
    def test_load_profile_corrupted_json(self):
        """load_profile() returns None if profile.json is malformed."""
        # arrange: profile.json = "{ invalid json"
        # act: call store.load_profile()
        # assert: returns None (not raises)
        pass

    def test_load_profile_missing_required_field(self):
        """load_profile() returns None if profile missing required field."""
        # arrange: profile.json valid JSON but missing 'name' field
        # act: call store.load_profile()
        # assert: returns None
        pass

    def test_save_profile_atomic_write(self):
        """save_profile() uses atomic write (temp + rename) to prevent corruption."""
        # arrange: profile to save
        # act: call store.save_profile(profile)
        # assert: original file unchanged if write fails midway
        pass

    def test_load_all_details_skips_malformed_activity(self):
        """load_all_details() returns dict with good activities, skips malformed."""
        # arrange: data/details/ has 5 activities, #3 corrupted
        # act: call store.load_all_details()
        # assert: returns {1: {...}, 2: {...}, 4: {...}, 5: {...}}
        pass
```

### 14. engine/insights.py — Pace context and fitness inference

```python
# tests/test_insights_context.py
import pytest
from datetime import date, timedelta
from paceforge.engine.insights import pace_context, infer_fitness
from paceforge.models.profile import UserFitnessProfile

class TestInsightsContext:
    def test_pace_context_empty_activities(self):
        """pace_context() returns None when no activities to compare against."""
        # arrange: profile with no recent activities
        # act: call pace_context(pace_sec_per_km=300)
        # assert: returns None
        pass

    def test_infer_fitness_single_activity_type(self):
        """infer_fitness() handles athletes with only one sport (run, bike, swim)."""
        # arrange: profile with only running activities
        # act: call infer_fitness()
        # assert: returns fitness level estimate, no cross-training warnings
        pass

    def test_infer_fitness_low_data_fallback(self):
        """infer_fitness() returns 'data_insufficient' if <2 weeks of history."""
        # arrange: profile with 1 activity from today
        # act: call infer_fitness()
        # assert: result.confidence < 0.5 or returns None
        pass

    def test_cross_training_impact_bike_to_run(self):
        """insights account for bike TSS when predicting run readiness."""
        # arrange: heavy bike session (TSS 150), then easy run scheduled
        # act: compute training recommendations
        # assert: run recommendation accounts for bike fatigue
        pass
```

### 15. cli.py — Command dispatch and error handling

```python
# tests/test_cli_error_cases.py
import pytest
from io import StringIO
from unittest.mock import patch
from paceforge import cli

class TestCLIErrorCases:
    def test_cli_command_not_found(self):
        """cli raises 'unknown command' error for invalid command."""
        # arrange: argv = ['paceforge', 'invalid_command']
        # act: call cli.main(argv)
        # assert: returns non-zero exit code
        pass

    def test_cli_missing_required_argument(self):
        """plan command requires --goal and --date."""
        # arrange: argv = ['paceforge', 'plan']
        # act: call cli.main(argv)
        # assert: stderr contains usage info, exit code non-zero
        pass

    def test_cli_json_output_format(self):
        """cli --format json returns valid JSON."""
        # arrange: argv = ['paceforge', 'brief', '--format', 'json']
        # act: call cli.main(argv)
        # assert: output is valid JSON (parseable)
        pass

    def test_cli_token_error_guidance(self):
        """login error message guides user to use 'paceforge login'."""
        # arrange: sync with no Garmin token
        # act: call actions.sync()
        # assert: error mentions 'paceforge login'
        pass
```

---

## Summary of Gaps

| Gap Type | Count | Impact | Effort |
|----------|-------|--------|--------|
| Untested functions (core logic) | 45+ | CRITICAL | 20h |
| Missing edge case tests | 80+ | HIGH | 15h |
| Failing skeleton tests (actions/analytics/garmin) | 26 | HIGH | 6h |
| Error path coverage | 30+ | MEDIUM | 10h |
| Integration tests (cross-module) | 12 | MEDIUM | 8h |

**Path to 85% coverage:**
1. Fix 26 failing skeletons (6 hours) → ~82%
2. Add 15 edge case tests (8 hours) → ~84%
3. Complete error path coverage (8 hours) → ~85%

---

## Testing Checklist

- [ ] Run failing tests to identify root causes
- [ ] Implement test skeletons 1-5 (hyrox, analytics base)
- [ ] Implement skeletons 6-10 (actions, garmin auth)
- [ ] Implement skeletons 11-15 (advanced flows)
- [ ] Fix model field mismatches in assertions
- [ ] Add integration tests for end-to-end sync/plan/push
- [ ] Verify coverage reaches 85% overall

---

## Files Needing Immediate Attention

1. `/home/azureuser/projects/paceforge/src/paceforge/hyrox/scraper.py` — 35% coverage
2. `/home/azureuser/projects/paceforge/src/paceforge/engine/analytics.py` — 60% coverage
3. `/home/azureuser/projects/paceforge/src/paceforge/garmin/client.py` — 64% coverage
4. `/home/azureuser/projects/paceforge/tests/test_actions_integration.py` — 26 failing
5. `/home/azureuser/projects/paceforge/tests/test_analytics_gaps.py` — 18 failing
6. `/home/azureuser/projects/paceforge/tests/test_garmin_client_auth.py` — 17 failing
