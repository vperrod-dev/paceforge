# PaceForge Test Coverage Gaps Analysis

**Baseline Coverage:** 72% overall (6024 statements, 1660 untested)

## Critical Gaps (0-40% coverage)

### 1. `cli.py` - 0% (132 stmts, ALL untested)

**Status:** Command-line interface completely untested

**Untested Functions:**
- `main()` — argument parsing, command dispatch (lines 20-182)
- `_emit()` — JSON/text output serialization (line 184-189)

**Test Gap Reason:** No integration tests for CLI commands

**Critical Paths Missing:**
- Login flow with MFA handling
- Sync with configurable lookback + details limit
- Plan scaffolding with goal/date/level/days
- Status/analyze/validate output
- Push to Garmin (--week, --dry-run)
- Autosync with calendar reconciliation
- Recalibrate with pace delta guard
- Adapt with missed-session reflow

**Why It Matters:** CLI is the user-facing entry point; untested commands can silently fail or lose data

---

### 2. `analytics.py` - 18% (611 stmts, 503 untested)

**Status:** Analytics computation mostly untested; only high-level tests exist

**Untested Functions:**
- `_estimate_vdot()` (line 150-184) — VDOT prediction from race results
- `_predict_race_time()` (line 187-211) — pace prediction via Riegel
- `compute_athlete_snapshot()` (line 217-314) — athlete summary aggregation
- `compute_aerobic_analysis()` (line 316-403) — VO2max trends + aerobic power
- `compute_running_economy()` (line 405-512) — efficiency analysis
- `compute_load_recovery()` (line 514-613) — CTL/ATL/TSB computation
- `compute_race_predictions()` (line 615-727) — multi-distance race estimates
- `compute_hyrox_predictions()` (line 729-884) — obstacle-race predictions
- `compute_training_recommendations()` (line 886-1009) — workout suggestions

**Test Gap Reason:** No unit tests; only indirect testing via high-level flow tests

**Edge Cases Missing:**
- No activity history → null predictions
- Single activity → boundary-case VDOT
- Recent hard effort without baseline → volatility handling
- Negative recovery (TSB < -50) → overtraining verdict
- Division by zero in running economy (zero time or distance)
- Future activities in history → date filtering
- Stale data (>365 days old) → trend confidence

**Why It Matters:** Analytics are core to coaching decision-making; wrong VDOT or recovery signals misguide training

---

### 3. `hyrox/scraper.py` - 35% (262 stmts, 170 untested)

**Status:** Web scraper largely untested; network mocking incomplete

**Untested Functions:**
- `_parse_leaderboard()` (line 85-87)
- `_extract_segment_times()` (line 106)
- `_normalize_time_string()` (line 119, 127)
- `_fetch_leaderboard_page()` (line 141-143)
- `scrape_leaderboard()` (line 168-199) — main public API
- `scrape_segment_standards()` (line 209-223)
- `_geocode_hyrox()` (line 238-273)
- `scrape_race_schedule()` (line 277-309)
- `search_athlete_results()` (line 319, 330)

**Test Gap Reason:** Network calls stubbed; HTML parsing not exercised with real/varied layouts

**Edge Cases Missing:**
- Malformed HTML (missing fields)
- Network timeouts (retries logic)
- 404/403 responses
- Pagination beyond first page
- Different date formats across regions
- Athlete with no recorded times
- Empty leaderboard

**Why It Matters:** Scraper failures silently return incomplete data; athletes lose benchmark context

---

### 4. `garmin/client.py` - 57% (644 stmts, 280 untested)

**Status:** Garmin API client partially tested; auth + sync untested

**Untested Functions:**
- `_login_flow()` (line 203-262) — OAuth handshake + MFA handling
- `_mfa_verify()` (line 269-271)
- `_extract_metrics()` (line 290-292)
- `_compute_load_focus()` (line 300-305)
- `fetch_wellness()` (line 312) — daily stats
- `fetch_activities()` (line 372-376) — activity list fetch
- `_parse_fit_file()` (line 387-418)
- `_parse_workout_file()` (line 432-443)
- `fetch_activity_details()` (line 454-460) — heartrate splits
- `_download_fit()` (line 468-498)
- `_upload_workout()` (line 505-523)
- `upload_structured_workout()` (line 538-547) — pace/HR targets
- `_build_steps()` (line 582-583)
- `push_workout()` (line 590-591)
- `delete_workout()` (line 648-689)
- `delete_all_workouts()` (line 703)

**Test Gap Reason:** Live Garmin API; stubbed in tests but error paths not exercised

**Critical Paths Missing:**
- Token refresh on 401
- Rate-limit backoff (429)
- Malformed JSON response → parse error
- Missing optional fields in wellness
- Duplicate activity ID handling
- Workout step constraint validation (pace bands, HR zones)
- Concurrent delete requests

**Why It Matters:** Sync failures cause data loss; malformed uploads corrupt Garmin calendar

---

## High-Coverage Gaps (75-90% coverage)

### 5. `store.py` - 75% (207 stmts, 52 untested)

**Untested Functions:**
- `_write()` — atomic file writes (line 24-30)
- `save_profile()` merge logic (line 41-56) — null preservation
- `append_daily_history()` → history.jsonl upsert (line 76-107)
- `repair_history()` — dedupe + schema migration (line 108-133)
- `upsert_rpe()` — RPE entry upsert (line 150-165)
- `rpe_by_activity()` — RPE index rebuild (line 166-171)
- `load_token_meta()` / `save_token_meta()` (line 172-185)
- `load_sync_status()` / `save_sync_status()` (line 187-200)
- `load_all_details()` — detail file merge (line 202-217)
- `save_hyrox_results()` (line 255-259)
- `save_hyrox_preview()` (line 260-264)

**Edge Cases Missing:**
- Concurrent writes → race condition
- Corrupt JSON file → model_validate error
- Missing directories → mkdir behavior
- Atomic write failure → .tmp cleanup
- Load non-existent file → None vs exception
- History row merge with partial nulls
- Schema migration on version mismatch

**Why It Matters:** Data corruption is permanent; atomic writes protect against crashes

---

### 6. `actions.py` - 74% (748 stmts, 192 untested)

**Untested Functions:**
- `login()` interactive flow (line 97-110) — getpass, MFA token
- `_token_age_days()` (line 112-122)
- `export_token()` (line 124-133) — base64 export
- `_ask()` — stdin prompt (line 91-95)
- `brief()` output formatting (line 295-340) — HTML/Telegram variants
- `_esc_html()` (line 342-344)
- `_fmt_mss()` — time formatting (line 346-349)
- `_step_pace_band()` (line 351-376)
- `_readiness_verdict()` (line 368-383)
- `_brief_telegram()` (line 385-432)
- `_match_plan()` (line 435-451)
- `_extract_series()` (line 453-503) — timeseries decimation
- `_trim_detail()` (line 505-553)
- `_sync_details()` (line 555-604) — N+1 detail fetching loop
- `calendar_edit()` (line 610-617)
- `garmin_delete()` (line 628-636)
- `push()` (line 641-644)
- `recalibrate()` (line 649-703) — pace shift validation
- `adapt()` (line 778-791)
- `garmin_reconcile()` (line 795-798)
- `scaffold()` (line 814-842)
- `plan_md()` (line 843-880)
- `validate()` (line 882-892)
- `analyze()` (line 893-904)
- `status()` (line 905-963)
- `autosync()` (line 964-1014)

**Edge Cases Missing:**
- Login with invalid MFA
- No Garmin token dir
- Sync with zero activities
- Push when plan is invalid
- Recalibrate without accepted plan
- Adapt with no missed sessions
- Analyze with missing profile

**Why It Matters:** Actions are job entry points; silent failures → missed sync cycles

---

### 7. `planner.py` - 80% (406 stmts, 81 untested)

**Untested Lines:** 195-204, 206-218, 250-252, 276, 377, 509, 512-513, 639, 667-675, 679-684, 689-695, 700-706, 713-720, 735, 737-741, 743, 745, 747, 750-753, 755-761, 763-769, 784, 825

**Functions Likely Untested:**
- Long-run rotation edge cases (consecutive > 3)
- Back-to-back hard sessions validation
- Hyrox-specific phase sequencing
- Goal feasibility checks (pace ordering)
- Volume ramp constraints

**Why It Matters:** Malformed plans → athlete overtraining or insufficient stimulus

---

### 8. `insights.py` - 80% (128 stmts, 25 untested)

**Untested Functions:**
- `compute_readiness_gate()` — hard-workout gating (line 50-54, 61, 70, 91, 101-109, 116, 121)
- `compute_compliance()` (line 142)
- `compute_status()` (line 152, 175-177, 210-211)

**Edge Cases Missing:**
- High training load + low readiness → gate active
- Recent hard effort → fatigue holdover
- No recent activities → neutral verdict

---

### 9. `validate.py` - 84% (156 stmts, 25 untested)

**Untested Lines:** 113, 159, 200, 231, 258-262, 268-303, 307

**Functions Likely Untested:**
- `validate_workout()` edge cases (pace bounds, HR targets)
- `validate_week()` consecutive-session checks
- `validate_plan()` error messages for multiple violations

---

## Integration Test Gaps

### Missing Cross-Module Tests

1. **Sync → Plan Flow**
   - Load activities → compute VDOT → scaffold plan → write to disk
   - Verify activities linked correctly

2. **Plan → Push Flow**
   - Load plan → build Garmin steps → upload → verify calendar

3. **Adapt → Sync Flow**
   - Adapt missed sessions → write plan → autosync reconcile

4. **Load Recovery → Recalibrate Flow**
   - Compute TSB → readiness decision → recalibrate gating

5. **Hyrox Import → Prediction Flow**
   - Scrape results → import → compute predictions → verify formulas

---

## Test Skeleton Template

```python
# tests/test_[module].py

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from paceforge.[module] import [function]
from paceforge.models import [Model]


class Test[FunctionName]:
    """[Purpose: one-sentence summary]"""

    def setup_method(self):
        """Prepare fixtures."""
        self.fixture = ...

    def test_happy_path(self):
        """[FunctionName] succeeds with valid inputs."""
        result = [function](self.fixture)
        assert result == expected

    def test_edge_case_[condition](self):
        """[FunctionName] handles [specific boundary]."""
        # Arrange
        input_data = ...
        # Act
        result = [function](input_data)
        # Assert
        assert result == expected or isinstance(result, ExpectedException)

    def test_error_[path](self):
        """[FunctionName] raises [exception] on [error condition]."""
        with pytest.raises([ExceptionType]) as exc:
            [function](invalid_input)
        assert "[error message substring]" in str(exc.value)

    @patch('paceforge.[module].[dependency]')
    def test_integration_[scenario](self, mock_dep):
        """[FunctionName] correctly calls [dependency]."""
        mock_dep.return_value = ...
        result = [function](input)
        mock_dep.assert_called_once_with(expected_args)
        assert result == expected
```

---

## Priority Test Implementation Order

1. **CRITICAL** (blocks other testing):
   - `store._write()` atomic write validation
   - `garmin.client.fetch_wellness()` error handling
   - `cli.main()` command dispatch (all 8 commands)

2. **HIGH** (core logic):
   - `actions.sync()` with detail limit
   - `actions.push()` with week selection
   - `analytics.compute_load_recovery()` TSB formula
   - `planner.generate_plan()` volume anchoring
   - `hyrox.scraper.scrape_leaderboard()` parsing

3. **MEDIUM** (supporting flows):
   - `actions.brief()` formatting variants
   - `actions.recalibrate()` validation
   - `store.append_daily_history()` merge
   - `validate.validate_plan()` multi-error reporting

4. **LOW** (utility):
   - `actions._trim_detail()` payload shrinking
   - `insights.compute_readiness_gate()` thresholds
   - `compliance.py` edge cases

---

## Coverage Target by Module

| Module | Current | Target | Gap |
|--------|---------|--------|-----|
| cli.py | 0% | 90% | +132 stmts |
| analytics.py | 18% | 80% | +350+ stmts |
| scraper.py | 35% | 80% | +115 stmts |
| garmin/client.py | 57% | 85% | +180 stmts |
| store.py | 75% | 95% | +45 stmts |
| actions.py | 74% | 85% | +80 stmts |
| planner.py | 80% | 90% | +40 stmts |
| **Overall** | **72%** | **85%** | **~1000 stmts** |

---

## Test Skeleton Inventory

### Provided Below (9 Test Files):

1. `test_cli.py` — 8 command tests
2. `test_analytics.py` — 10 function tests
3. `test_scraper.py` — 6 parsing tests
4. `test_garmin_client_auth.py` — auth + error handling
5. `test_store_atomicity.py` — file I/O safety
6. `test_actions_integration.py` — sync/push/adapt flows
7. `test_planner_edge_cases.py` — plan generation boundaries
8. `test_validate_comprehensive.py` — multi-error detection
9. `test_insights_readiness.py` — gate logic + thresholds
