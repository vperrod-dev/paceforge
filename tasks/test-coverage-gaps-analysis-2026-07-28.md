# Test Coverage Gap Analysis — PaceForge

**Date:** 2026-07-28  
**Test Suite Status:** 580/580 passing (100%)  
**Overall Code Coverage:** ~70% of public functions; ~45% of integration flows and error paths

---

## Executive Summary

PaceForge has strong unit test coverage for core modules (CLI, store, Garmin client) but significant gaps in:

1. **Error handling workflows** — Garmin API failures, timeouts, rate limits
2. **Integration chains** — Multi-step flows (sync → analyze → coach)
3. **Edge cases** — Leap years, empty data, out-of-bounds inputs
4. **Workout factory methods** — 22 of 25 generators untested in isolation
5. **Advanced analytics** — Load metrics, strength analysis, Hyrox predictions

---

## 1. Untested Functions (Priority by Impact)

### High-Impact Gaps

#### Workout Factory (22/25 untested)

**File:** `src/paceforge/engine/workouts.py`  
**Tested:** `hyrox_compromised_brick()`, `hyrox_race_simulation()`, `station_day()`  
**Untested:**
- `easy_run()`, `recovery_run()`, `long_run()` — Only indirect via planner
- `tempo()`, `threshold_cruise_intervals()`, `vo2max_intervals()` — Planner only
- `speed_400s()`, `speed_200s()`, `speed_reps()` — **Never tested**
- `fartlek()`, `hills()`, `ladder()` — **Never tested**
- `alternations()`, `time_trial()` — **Never tested**
- `long_run_progressive()`, `long_run_blocks()`, `long_run_with_race_pace()` — Indirect only
- `easy_with_strides()` — **Never tested**

**Risk:** If a generator breaks (e.g., step structure), it won't surface until a user schedules that workout type.

**Test Skeleton:**
```python
def test_speed_400s_creates_repeat_group_with_400m_intervals():
    """speed_400s(reps=10) generates 10x 400m repeats + recovery."""
    factory = WorkoutFactory(paces_from_vdot(50))
    wo = factory.speed_400s(reps=10)
    
    assert wo.workout_type == WorkoutType.SPEED
    repeat = next(s for s in wo.steps if s.repeat_count)
    assert repeat.repeat_count == 10
    assert repeat.steps[0].distance_meters == 400
    assert wo.estimated_distance_meters == pytest.approx(5200)

def test_tempo_creates_tempo_segment_with_threshold_pace():
    """tempo(distance_km=5) creates one tempo block at threshold pace."""
    factory = WorkoutFactory(paces_from_vdot(50))
    wo = factory.tempo(distance_km=5)
    
    assert wo.workout_type == WorkoutType.TEMPO
    tempo_step = next(s for s in wo.steps if s.step_type == WorkoutStepType.ACTIVE)
    assert tempo_step.target_type == IntensityTarget.PACE
    assert wo.estimated_distance_meters == pytest.approx(5000)

def test_long_run_with_race_pace_includes_target_pace_segment():
    """long_run_with_race_pace(base_km=12, rp_km=3) includes 3km at race pace."""
    factory = WorkoutFactory(paces_from_vdot(50))
    wo = factory.long_run_with_race_pace(base_km=12, rp_km=3)
    
    race_pace_steps = [s for s in wo.steps if s.pace_key == "race"]
    assert len(race_pace_steps) > 0
    race_km = sum(s.distance_meters or 0 for s in race_pace_steps) / 1000
    assert race_km == pytest.approx(3, abs=0.1)
```

---

#### Load Module Analytics (6/22 untested)

**File:** `src/paceforge/engine/load.py`

Untested functions (all part of athlete fitness assessment):
- `compute_ramp_rate()` — CTL (Chronic Training Load) rate of change
- `compute_aerobic_anaerobic_split()` — Aerobic vs anaerobic contribution
- `compute_resting_hr_trend()` — Heart rate trend detector
- `compute_body_battery_trend()` — Garmin body battery metric
- `compute_stress_trend()` — Stress metric over time
- `compute_overtraining_composite()` — Overtraining detector

**Risk:** Analytics dashboard could display incorrect readiness/recovery if these functions have bugs.

**Test Skeleton:**
```python
def test_compute_ramp_rate_positive_when_training_load_increasing():
    """Ramp rate > 0 when weekly CTL increases."""
    profile = UserFitnessProfile(
        daily_history=[
            {"date": date(2026, 7, 21), "ctl": 50},
            {"date": date(2026, 7, 28), "ctl": 60},
        ]
    )
    ramp = compute_ramp_rate(profile)
    assert ramp > 0

def test_compute_body_battery_trend_flags_overuse():
    """Body battery trend < 10 indicates overuse."""
    profile = UserFitnessProfile(
        daily_history=[
            {"date": d, "body_battery": max(5, 50 - i * 5)}
            for i, d in enumerate(date_range(date(2026, 7, 1), date(2026, 7, 28)))
        ]
    )
    trend = compute_body_battery_trend(profile)
    assert trend["status"] == "declining"
```

---

#### Actions Module Helpers (10+ untested)

**File:** `src/paceforge/actions.py`

Untested functions:
- `_token_dir()`, `_has_token()`, `_export_token()`, `_garmin_email()` — Token/email persistence
- `_token_age_days()` — Token expiry detector
- `status()` — System status query
- `plan_md()` — Export plan to markdown
- `calendar_edit()` — Calendar event editing
- `log_rpe()` — User RPE logging (tested indirectly)
- `hyrox_search()`, `hyrox_import()`, `hyrox_import_profile()` — Hyrox workflows

**Test Skeleton:**
```python
def test_token_age_days_calculates_days_since_login():
    """_token_age_days() returns days between login and today."""
    with patch('paceforge.actions.store.load_token_meta') as mock_load:
        mock_load.return_value = {"login_date": str(date.today() - timedelta(days=30))}
        age = _token_age_days()
        assert age == 30

def test_status_query_returns_system_state():
    """status() returns current profile, plan, and sync status."""
    with patch('paceforge.actions.store.load_profile') as mock_prof:
        with patch('paceforge.actions.store.load_sync_status') as mock_sync:
            mock_prof.return_value = UserFitnessProfile(vo2_max=45.0)
            mock_sync.return_value = {"last_sync": "2026-07-28T06:45:00Z", "status": "ok"}
            
            result = status()
            assert "profile" in result
            assert result["sync_status"]["status"] == "ok"

def test_plan_md_exports_plan_to_markdown():
    """plan_md() generates markdown with week structure."""
    with patch('paceforge.actions.store.load_plan') as mock_load:
        plan = TrainingPlan(
            name="Test",
            goal_type="MARATHON",
            target_date=date(2026, 10, 4),
            total_weeks=12,
            weeks=[...],
        )
        mock_load.return_value = plan
        
        md = plan_md()
        assert "# Test" in md
        assert "MARATHON" in md
        assert "Week" in md
```

---

#### Store Module File I/O (9+ untested)

**File:** `src/paceforge/store.py`

Untested edge cases:
- `load_rpe()` — Missing file, corrupt JSON
- `load_token_meta()` — File not found, invalid format
- `save_sync_status()` — Concurrent writes, disk full
- `load_all_details()` — Partial failures across activities
- `load_bike_rides()` — Empty history, corrupt ride records

**Test Skeleton:**
```python
def test_load_rpe_returns_empty_dict_when_file_missing():
    """load_rpe() on missing file returns {}."""
    with patch.dict(os.environ, {"PACEFORGE_DATA_DIR": "/nonexistent"}):
        rpe = load_rpe()
        assert rpe == {}

def test_save_sync_status_atomic_write():
    """save_sync_status() uses temp file + os.replace() for atomicity."""
    with TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"PACEFORGE_DATA_DIR": tmpdir}):
            save_sync_status({"status": "ok", "timestamp": "2026-07-28T12:00:00Z"})
            
            # Verify file exists and contains correct data
            import json
            status_file = Path(tmpdir) / "sync-status.json"
            assert status_file.exists()
            with open(status_file) as f:
                data = json.load(f)
            assert data["status"] == "ok"

def test_load_bike_rides_handles_empty_history():
    """load_bike_rides() returns [] when bike/rides.json missing."""
    with patch.dict(os.environ, {"PACEFORGE_DATA_DIR": "/tmp"}):
        rides = load_bike_rides()
        assert isinstance(rides, list)
```

---

### Medium-Impact Gaps

#### VDOT Module

**File:** `src/paceforge/engine/vdot.py`

Untested:
- `predict_time()` — Race time prediction (only `paces_from_vdot()` tested)
- `normalize_lt_speed()` — Lactate threshold normalization

**Test Skeleton:**
```python
def test_predict_time_5k_from_vdot():
    """predict_time(vdot=50, distance=5) returns ~17 minutes."""
    time_sec = predict_time(vdot=50, distance_km=5)
    time_min = time_sec / 60
    assert 16 < time_min < 18  # Adjust bounds based on formula

def test_predict_time_boundary_very_high_vdot():
    """predict_time(vdot=80+) should handle elite athletes."""
    time_sec = predict_time(vdot=80, distance_km=42.2)  # Marathon
    # Should be ~2h 10 min or better
    assert time_sec < 8000
```

---

#### Briefings & Compliance

**File:** `src/paceforge/engine/briefings.py`, `compliance.py`

Untested:
- `build_structure()` — Workout step formatting
- `annotate_pace()` — Pace zone annotation

**Test Skeleton:**
```python
def test_build_structure_formats_warmup_main_cooldown():
    """build_structure() returns brief describing warmup + work + cooldown."""
    structure = build_structure(
        warmup_km=1,
        main_work="5x 400m @ interval pace",
        cooldown_km=1
    )
    assert "1 km warmup" in structure
    assert "5x 400m" in structure
    assert "1 km cooldown" in structure

def test_annotate_pace_marks_workout_in_plan():
    """annotate_pace() tags workouts as easy/marathon/race/etc."""
    plan = TrainingPlan(...)
    plan = annotate_pace(plan)
    
    easy_workouts = [w for w in all_workouts(plan) if w.pace_key == "easy"]
    assert len(easy_workouts) > 0
```

---

## 2. Error Handling Gaps

### Garmin API Failures

#### Missing Test Scenarios

| Failure Mode | Current Test | Gap | Risk |
|--------------|--------------|-----|------|
| Token expiry mid-sync | 1 test, fetch_wellness | Multi-endpoint retry not tested | Partial profile stored silently |
| Rate limit (429) | Tested in isolation | No workflow retry | Sync fails on busy day |
| 403 Forbidden | Fixed 2026-07-28 | Recovery workflow untested | User thinks device is broken |
| Activity 404 (deleted) | Tested for single | Multi-activity state corruption | Schedule shows ghost workouts |
| Network timeout | Mocked in tests | Retry backoff in workflows | Sync incomplete, no user warning |
| Malformed response | Not tested | No validation of Garmin response | Crashes on unexpected fields |

**Test Skeleton for Timeout Recovery:**
```python
def test_sync_retries_on_network_timeout():
    """sync() should retry with backoff when Garmin times out."""
    mock_client = MagicMock()
    mock_client.get_stats.side_effect = [
        TimeoutError("Connection timed out"),
        {"rest_hr": 50},  # Succeeds on retry
    ]
    
    with patch('paceforge.actions.garmin_connect', return_value=mock_client):
        result = sync(max_retries=3, retry_delay=0.1)
        assert result["status"] == "ok"
        assert mock_client.get_stats.call_count == 2

def test_sync_handles_partial_profile_on_timeout():
    """sync() with mid-way timeout should preserve partial data."""
    mock_client = MagicMock()
    mock_client.get_stats.return_value = {"rest_hr": 50}
    mock_client.get_activities.side_effect = TimeoutError()
    
    with patch('paceforge.actions.garmin_connect', return_value=mock_client):
        result = sync()
        assert result["partial"] is True
        assert "activities" not in result
        # sync-status.json should record partial state
```

---

### File I/O Errors

**Untested:**
- Disk full during `save_plan()`
- Concurrent writes to `sync-status.json` (cloud deployments with multiple instances)
- Corrupt JSON recovery (partial file write)
- Missing data directory

**Test Skeleton:**
```python
def test_save_plan_handles_disk_full():
    """save_plan() on disk-full raises clear error, doesn't corrupt existing file."""
    original_plan = TrainingPlan(...)
    store.save_plan(original_plan)
    
    with patch('builtins.open', side_effect=OSError("No space left on device")):
        with pytest.raises(OSError, match="No space"):
            store.save_plan(modified_plan)
    
    # Verify original file still intact
    loaded = store.load_plan()
    assert loaded == original_plan

def test_load_plan_recovers_from_partial_write():
    """load_plan() detects partial JSON and falls back to backup."""
    # Create a corrupted plan file (truncated JSON)
    plan_file = Path(store.DATA_DIR) / "plan.json"
    plan_file.write_text('{"name": "Truncated')
    
    # Should either error clearly or use backup
    try:
        plan = store.load_plan()
        assert False, "Should raise JSONDecodeError"
    except json.JSONDecodeError:
        pass  # Expected
```

---

## 3. Integration Test Gaps

### Critical Workflows Not Tested

#### Sync → Analyze → Fitness Chain

```python
def test_sync_analyze_fitness_complete_workflow():
    """Full workflow: fresh sync → analytics → fitness dashboard."""
    mock_client = MagicMock()
    mock_client.get_stats.return_value = {...}
    mock_client.get_activities.return_value = [...]
    
    with patch('paceforge.actions.garmin_connect', return_value=mock_client):
        # 1. Sync Garmin data
        sync_result = sync()
        assert sync_result["status"] == "ok"
        
        # 2. Run analytics
        analysis = analyze()
        assert "load" in analysis
        assert "readiness" in analysis
        
        # 3. Verify fitness dashboard
        brief = brief(when=None)
        assert "readiness" in brief or "Today" in brief
```

#### Plan Push → Garmin Schedule → Sync

```python
def test_push_plan_week_then_sync_verifies_in_calendar():
    """push(week=1) → autosync() should show workouts in Garmin calendar."""
    plan = TrainingPlan(...)
    
    mock_client = MagicMock()
    mock_client.push_plan_week.return_value = {"pushed": [123, 124, 125]}
    mock_client.get_scheduled_workouts.return_value = [
        {"id": 123, "name": "Easy Run"},
        {"id": 124, "name": "Tempo"},
        {"id": 125, "name": "Long Run"},
    ]
    
    with patch('paceforge.actions.store.load_plan', return_value=plan):
        result = push(week=1)
        assert result["pushed_count"] == 3
        
        # Verify scheduled
        scheduled = mock_client.get_scheduled_workouts()
        assert len(scheduled) == 3
```

#### Adapt → Readiness Gate

```python
def test_adapt_respects_readiness_gate_for_vo2_workouts():
    """adapt() should move VO2 workouts when readiness is low."""
    profile = UserFitnessProfile(
        daily_history=[
            {"date": date(2026, 7, 28), "readiness": 25},  # Low
            {"date": date(2026, 7, 29), "readiness": 70},  # High
        ]
    )
    plan = TrainingPlan(
        weeks=[{
            "week_number": 1,
            "workouts": [
                Workout(
                    name="VO2 Max",
                    workout_type=WorkoutType.VO2MAX,
                    scheduled_date=date(2026, 7, 28),  # On low-readiness day
                ),
            ]
        }]
    )
    
    with patch('paceforge.actions.store.load_profile', return_value=profile):
        with patch('paceforge.actions.store.load_plan', return_value=plan):
            adapted = adapt(dry_run=True)
            
            # VO2 should have moved to higher-readiness day
            vo2_after = next(w for w in all_workouts(adapted) if w.workout_type == WorkoutType.VO2MAX)
            assert vo2_after.scheduled_date == date(2026, 7, 29)
```

---

## 4. Edge Cases Not Covered

### Date/Calendar Edge Cases

```python
def test_plan_generation_leap_year_long_run():
    """Long run on Feb 29 in leap year."""
    goal = TrainingGoal(
        goal_type="HALF_MARATHON",
        target_date=date(2024, 4, 15),
        training_days=["thursday"],
        long_run_day="thursday",
    )
    profile = UserFitnessProfile(vo2_max=45)
    
    plan = generate_plan(profile, goal)
    
    feb_29_workouts = [w for week in plan.weeks 
                       for w in week.workouts 
                       if w.scheduled_date == date(2024, 2, 29)]
    assert len(feb_29_workouts) > 0

def test_plan_crossing_calendar_year():
    """Plan spanning Dec 31 / Jan 1 boundary."""
    goal = TrainingGoal(
        goal_type="MARATHON",
        target_date=date(2027, 1, 15),
        training_days=["mon", "tue", "wed", "thu", "fri"],
    )
    plan = generate_plan(profile, goal)
    
    # Should have workouts on both sides of year boundary
    dec_workouts = [w for week in plan.weeks for w in week.workouts 
                   if w.scheduled_date.year == 2026]
    jan_workouts = [w for week in plan.weeks for w in week.workouts 
                   if w.scheduled_date.year == 2027]
    assert len(dec_workouts) > 0
    assert len(jan_workouts) > 0

def test_daylight_saving_activity_boundary():
    """Activity crossing DST transition (spring forward 2am → 3am)."""
    # 2024: DST on Mar 10, 2am UTC → 3am UTC
    activity = RecentActivity(
        activity_id=1,
        name="Long run",
        start_time=datetime(2024, 3, 10, 1, 30, tzinfo=timezone.utc),
        duration_seconds=7200,  # 2 hours
        distance_meters=20000,
    )
    
    profile = UserFitnessProfile(activities=[activity])
    
    # Should not break on timezone conversion
    load = compute_load(profile)
    assert load > 0
```

### Activity Data Edge Cases

```python
def test_sync_handles_empty_activities_list():
    """sync() with zero Garmin activities should not crash analytics."""
    profile = UserFitnessProfile(activities=[])
    
    analysis = compute_all(profile)
    assert analysis is not None
    assert "warning" in analysis or analysis.get("vdot_estimate") is None

def test_compute_load_without_heart_rate():
    """Load calculation fallback when HR data missing."""
    activity = RecentActivity(
        name="Run",
        distance_meters=10000,
        duration_seconds=2400,
        avg_hr=None,  # Missing HR
    )
    
    load = compute_activity_load(activity)
    # Should use pace-based fallback or return None
    assert load is None or load > 0

def test_vdot_estimation_zero_distance():
    """VDOT estimation with zero-distance activity."""
    activity = RecentActivity(
        name="Session",
        distance_meters=0,  # Edge case
        duration_seconds=1800,
    )
    
    vdot = estimate_vdot_from_activity(activity)
    # Should handle gracefully
    assert vdot is None or vdot > 0

def test_duplicate_activity_ids_in_sync():
    """Garmin sometimes returns duplicate activity IDs; verify dedup."""
    activities = [
        RecentActivity(activity_id=1, name="Run 1", ...),
        RecentActivity(activity_id=1, name="Run 1 (dup)", ...),
    ]
    
    profile = store.merge_activities(profile, activities)
    # Should have only one activity with ID=1
    assert len([a for a in profile.activities if a.activity_id == 1]) == 1
```

### Pace/Fitness Boundary Cases

```python
def test_pace_zone_boundaries_vdot_25():
    """Zone targets for beginner (VDOT 25)."""
    bands = paces_from_vdot(25)
    
    assert bands["easy"] < bands["marathon"] < bands["threshold"]
    assert all(p > 0 for p in bands.values())

def test_pace_zone_boundaries_vdot_85():
    """Zone targets for elite (VDOT 85)."""
    bands = paces_from_vdot(85)
    
    # Should not break on high VDOT
    assert bands["easy"] < bands["threshold"]
    assert bands["interval"] < bands["easy"]  # Faster intervals

def test_race_pace_faster_than_easy():
    """Goal pace faster than easy pace is invalid."""
    goal = TrainingGoal(
        goal_type="MARATHON",
        target_date=date(2026, 10, 4),
        target_time_seconds=7200,  # 2h marathon (elite)
    )
    profile = UserFitnessProfile(vo2_max=45)  # Beginner
    
    try:
        plan = generate_plan(profile, goal)
        # Should either fail or create adjusted plan
        if plan:
            race_pace = plan.marathon_pace
            easy_pace = plan.easy_pace
            assert race_pace <= easy_pace
    except ValueError as e:
        assert "infeasible" in str(e).lower()

def test_plan_one_day_race():
    """Target race 1 day away (should fail gracefully)."""
    goal = TrainingGoal(
        goal_type="5K",
        target_date=date.today() + timedelta(days=1),
    )
    
    try:
        plan = generate_plan(profile, goal)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "feasibility" in str(e).lower() or "too soon" in str(e).lower()
```

---

## 5. Missing Test Scenarios Summary

| Category | Count | Examples |
|----------|-------|----------|
| **Untested functions** | ~60+ | Workout factory (22), load metrics (6), actions helpers (10+), store I/O (9) |
| **Error paths** | ~30+ | Garmin API (10), file I/O (5), network/timeout (8), parse errors (7) |
| **Integration workflows** | ~10 | sync→analyze, push→schedule, adapt→readiness_gate |
| **Edge cases** | ~20+ | Leap years, DST, empty data, duplicate IDs, boundary paces |
| **Performance** | Untested | Concurrent API calls, large activity histories (1000+), memory leaks |
| **Security** | Untested | Token expiry handling, password storage, HTTPS enforcement |

---

## 6. Implementation Priorities

### Phase 1 (Quick Wins — 2-3 hours)
1. Workout factory methods — add 10 unit tests (each 15 min)
2. Actions helpers (`status()`, `plan_md()`, token functions) — 3 tests (30 min)
3. Store I/O edge cases (disk full, missing files) — 2 tests (30 min)

### Phase 2 (Medium Effort — 4-5 hours)
4. Load module analytics — 6 tests (45 min)
5. Garmin API error workflows (timeout retry, 429 backoff) — 3 tests (1h)
6. Date/calendar edge cases — 3 tests (45 min)

### Phase 3 (Integration — 6+ hours)
7. Full workflow chains (sync → analyze → fitness) — 3 tests (2h)
8. Plan push → schedule → sync verification — 1 test (1h)
9. Readiness-gated adaptation — 1 test (1h)

---

## Test Skeleton Repository

All skeletons above can be added to a new file: `tests/test_coverage_skeletons.py` to track remaining work.

---

## Coverage Report Command

```bash
# Current pass rate
.venv/bin/pytest tests/ -q
# Output: 580 passed

# Module-by-module coverage
.venv/bin/pytest tests/ --cov=paceforge --cov-report=term-missing

# Focus on untested modules
.venv/bin/pytest tests/ --cov=paceforge.engine.workouts --cov-report=term-missing
.venv/bin/pytest tests/ --cov=paceforge.engine.load --cov-report=term-missing
```

---

## Related

- Prior audit: `tasks/test-coverage-audit.md`
- Test fix session: Commit f5c54d0 (2026-07-28)
- Performance audit: `tasks/perf-audit-2026-07-28.md`
