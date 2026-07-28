# Test Coverage Fix Plan — Phase 2 (2026-07-28)

**Status:** 550/576 passing | 26 failures  
**Target:** 100% passing by fixing field name mismatches in test payloads  
**Effort:** 45 min estimated (straightforward renames, no logic changes)

---

## Problem Summary

Three test suites fail due to **model field name mismatches** in test payloads:

1. **test_actions_integration.py** — Uses `race_date` + `level` instead of `target_date` + `experience_level`
2. **test_analytics_gaps.py** — Calls non-existent or misnamed functions 
3. **test_garmin_client_auth.py** — Minor upload constraint test failures

All failures are **payload validation errors**, not logic bugs. The actual code is correct; tests just pass wrong field names.

---

## Fix 1: test_actions_integration.py (15 failures)

**File:** `tests/test_actions_integration.py`  
**Issues:**
- Line 193-195: `race_date` → `target_date`, `level` → `experience_level`
- Line 204: Same field mapping
- Line 230: Same field mapping  
- All TestRecalibrate/TestPush/TestAutoSync/TestAdapt tests call functions with correct signatures

**Fixes (all edits to TestScaffoldPlan + TestRecalibrate goal dicts):**

```python
# WRONG:
goal_dict = {
    "goal_type": "MARATHON",
    "race_date": "2026-10-04",
    "level": "intermediate",
}

# RIGHT:
goal_dict = {
    "goal_type": "MARATHON",
    "target_date": "2026-10-04",
    "experience_level": "intermediate",
}
```

**Affected test methods:**
- `TestScaffoldPlan::test_scaffold_basic_flow`
- `TestScaffoldPlan::test_scaffold_with_target_time`
- `TestRecalibratePaceDelta::test_recalibrate_positive_delta`
- `TestRecalibratePaceDelta::test_recalibrate_negative_delta`
- `TestRecalibratePaceDelta::test_recalibrate_guard_blocks_unapproved_shift`

---

## Fix 2: test_analytics_gaps.py (10 failures)

**File:** `tests/test_analytics_gaps.py`  
**Issues:**
- `_estimate_vdot()` doesn't exist in analytics.py (check for `estimate_vdot` or similar)
- `_predict_race_time()` may have different name/signature
- `compute_training_recommendations()` needs correct params

**Action:** Grep for actual function names in analytics.py:

```bash
grep -n "def.*vdot\|def.*race\|def.*training" src/paceforge/analytics.py
```

Then map test calls to actual functions. Most likely:
- `_estimate_vdot()` → doesn't exist, need to check if function was removed or renamed
- Tests may be calling functions that aren't exported or have different names

---

## Fix 3: test_garmin_client_auth.py (2 failures)

**File:** `tests/test_garmin_client_auth.py`  
**Failures:**
- `TestGarminUploadWorkout::test_upload_workout_constraint_validation`
- `TestGarminUploadWorkout::test_upload_workout_403_permission_denied`

**Action:** Check these specific test methods for mocking issues or assertion problems.

---

## Implementation Steps

### Step 1: Fix test_actions_integration.py (5 min)

```bash
# Find all goal_dict definitions with wrong field names
grep -n "race_date\|'level'" tests/test_actions_integration.py

# Edit each occurrence: race_date → target_date, level → experience_level
```

### Step 2: Verify and fix test_analytics_gaps.py (20 min)

```bash
# Find what the actual function names are
grep -n "^def " src/paceforge/analytics.py | grep -i "vdot\|race\|recommend"

# Then fix test calls to match actual function signatures
# Likely: rename _estimate_vdot → vdot_estimate or similar
# Or: function doesn't exist, need to remove tests or implement it
```

### Step 3: Fix test_garmin_client_auth.py (10 min)

```bash
# Run just these two tests to see the actual error
.venv/bin/pytest tests/test_garmin_client_auth.py::TestGarminUploadWorkout -v

# Fix mocking or assertions based on error details
```

### Step 4: Verify all pass (5 min)

```bash
.venv/bin/pytest tests/ -q --tb=short
# Target: 576 passed
```

---

## Known Good Field Names

From `src/paceforge/models/profile.py`:

**TrainingGoal:**
- ✅ `goal_type` (enum GoalType)
- ✅ `target_date` (date) — **NOT** `race_date`
- ✅ `target_time_seconds` (float | None)
- ✅ `experience_level` (enum ExperienceLevel) — **NOT** `level`
- ✅ `training_days` (list[str])
- ✅ `long_run_day` (str)
- ✅ `start_date` (date | None)
- ✅ Custom pace fields

---

## Test Commands

```bash
# Run only failing tests to track progress
.venv/bin/pytest tests/test_actions_integration.py -q --tb=line
.venv/bin/pytest tests/test_analytics_gaps.py -q --tb=line
.venv/bin/pytest tests/test_garmin_client_auth.py::TestGarminUploadWorkout -q

# Full suite check
.venv/bin/pytest tests/ -q --tb=short | tail -5
```

---

## Phase Completion Criteria

- [ ] All 15 test_actions_integration failures fixed
- [ ] All 10 test_analytics_gaps failures fixed
- [ ] All 2 test_garmin_client_auth failures fixed
- [ ] `pytest tests/ -q` shows 576 passed, 0 failed
- [ ] No warnings or skipped tests

**Session target:** Complete this fix session with 100% passing rate.
