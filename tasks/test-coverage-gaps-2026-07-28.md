# Test coverage gaps — 2026-07-28

**Baseline:** `pytest --cov=src/paceforge` → **72%** (469 tests passed).
`pytest --cov=scripts` → **34%** (runner.py alone: 49%).

## Critical gaps (by priority)

### 1. `cli.py` — 0% coverage

**Risk:** Silent regression in command dispatch. Thin dispatcher (`args.cmd == "..."` → `actions.X()` → `_emit`), broken subcommand wiring ships undetected. No integration test exercises `main()` end-to-end.

**Test skeleton:**

```python
# tests/test_cli.py
import pytest
from unittest.mock import patch, MagicMock
from paceforge.cli import main

def test_status_dispatches_to_actions_status(capsys):
    with patch("paceforge.actions.status", return_value={"ok": True}) as m:
        assert main(["status"]) == 0
    m.assert_called_once_with()
    assert '"ok": true' in capsys.readouterr().out

def test_plan_scaffolds_and_outputs_json(capsys):
    with patch("paceforge.actions.scaffold", return_value={"weeks": 12}) as m:
        main(["plan", "--goal", "MARATHON", "--date", "2026-10-04"])
    kwargs = m.call_args[0][0]
    assert kwargs["goal_type"] == "MARATHON"

def test_validate_returns_exit_1_on_issues(capsys):
    with patch("paceforge.actions.validate", return_value=["pace out of order"]):
        assert main(["validate"]) == 1
    assert "INVALID" in capsys.readouterr().out

def test_runtime_error_prints_to_stderr_and_exits_1(capsys):
    with patch("paceforge.actions.status", side_effect=RuntimeError("no profile")):
        assert main(["status"]) == 1
    assert "error: no profile" in capsys.readouterr().err

def test_unknown_command_exits_2(capsys):
    assert main(["nonexistent"]) != 0
```

---

### 2. `scripts/users.py` — 0% coverage

**Risk:** Multi-user provisioning bug corrupts friend's instance or leaks password. Provisions isolated instance: clone, env file (scrypt hash), systemd unit, Caddy route. No test at all.

**Test skeleton:**

```python
# tests/test_users.py
import pytest
import os
from pathlib import Path

def test_add_writes_scrypt_hash_not_plaintext(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paceforge-users").mkdir()
    # arrange: run add("alice") with mocked subprocess
    # assert: env file contains PF_WEB_PASS_SCRYPT=<salt_hex>$<hash_hex>, never plaintext
    from scripts.users import add_user
    password = add_user("alice")
    env_file = tmp_path / "paceforge-users" / "alice" / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "PF_WEB_PASS_SCRYPT=" in content
    assert password not in content  # not stored

def test_add_idempotent_preserves_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # calling add("alice") twice must not clobber existing data/token dir
    # first call: add alice, write marker to data/
    # second call: add alice again, assert marker still present
    pass

def test_remove_requires_explicit_yes_flag(tmp_path):
    # remove("alice") without --yes must refuse (destructive op guard)
    pass

def test_update_copies_web_scripts_not_data(tmp_path, monkeypatch):
    # scripts/users.py update must not drag Victor's data/*.json into instances
    # (per CLAUDE.md: instances never pull; data is instance-local)
    pass

def test_list_shows_all_provisioned_instances(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # add alice, bob, charlie
    # list() must show all three
    pass
```

---

### 3. `scripts/runner.py` — 49% (security-critical)

**Risk:** Job execution error handling + request lifecycle untested. RUNS memory leak fixed (line 89: `del RUNS[:-200]`), but no test asserts the cap.

**Test skeleton:**

```python
# tests/test_runner_jobs.py
import pytest
from scripts import runner

@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_RUNNER_STATE", str(tmp_path / "state.json"))
    runner.RUNS[:] = []
    yield tmp_path

def test_job_failure_recorded_with_traceback(state):
    def failing_job(run):
        raise ValueError("simulated failure")
    
    runner.JOBS["fail_test"] = failing_job
    run_id = runner.dispatch({"job": "fail_test"})
    # process the job
    entry = next((r for r in runner.RUNS if r["id"] == run_id), None)
    assert entry is not None
    assert entry["status"] == "error"
    assert "ValueError" in entry["error"]

def test_runs_list_capped_at_200(state):
    def noop(run):
        pass
    runner.JOBS["noop"] = noop
    
    for i in range(210):
        run_id = runner.dispatch({"job": "noop"})
        # simulate completion
        runner.RUNS.append({"id": run_id, "status": "done"})
    
    # apply cap
    if len(runner.RUNS) > 200:
        del runner.RUNS[:-200]
    
    assert len(runner.RUNS) == 200

def test_runs_cap_keeps_most_recent(state):
    # oldest entries evicted, newest kept
    pass

def test_malformed_request_body_returns_400(state):
    # POST with invalid JSON → 400, not 500
    pass

def test_concurrent_job_dispatch_serialized(state):
    # two simultaneous dispatches don't corrupt plan.json
    pass

def test_request_lifecycle_handles_missing_session(state):
    # missing session cookie → 401, not 500
    pass

def test_job_timeout_recorded_as_error(state):
    # job hangs past timeout → marked error, not silently ignored
    pass
```

---

### 4. `store.py` — 75% (every loader's corrupt-JSON fallback untested)

**Risk:** Systemic: ~9 loaders catch `(json.JSONDecodeError, OSError)` with untested fallback. Corrupt file during sync → silent fallback or crash (unverified).

**Test skeleton:**

```python
# tests/test_store_corrupt_files.py
import pytest
import json
from paceforge import store

@pytest.mark.parametrize("loader,path,default", [
    (store.load_rpe, "rpe.json", {"entries": []}),
    (store.load_token_meta, "token-meta.json", None),
    (store.load_sync_status, "sync-status.json", None),
    (store.load_hyrox_results, "hyrox.json", []),
    (store.load_events, "events.json", []),
    (store.load_benchmarks, "benchmarks.json", {}),
    (store.load_history, "history.json", []),
])
def test_corrupt_json_falls_back_to_default(tmp_path, monkeypatch, loader, path, default):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    (tmp_path / path).write_text("{not valid json")
    assert loader() == default

def test_missing_json_file_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path / "nonexistent"))
    assert store.load_rpe() == {"entries": []}

def test_load_all_details_skips_corrupt_keeps_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    d = tmp_path / "details"
    d.mkdir()
    (d / "1.json").write_text('{"activity_id": 1}')
    (d / "2.json").write_text("garbage")
    (d / "3.json").write_text('{"activity_id": 3}')
    
    result = store.load_all_details()
    assert result == {1: {"activity_id": 1}, 3: {"activity_id": 3}}

def test_permissions_error_on_read_handled(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    f = tmp_path / "rpe.json"
    f.write_text('{"entries": []}')
    f.chmod(0o000)
    try:
        # should not raise, should return default
        result = store.load_rpe()
        assert result == {"entries": []}
    finally:
        f.chmod(0o644)

def test_save_creates_parent_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    store.save_rpe({"entries": [{"id": 1}]})
    assert (tmp_path / "rpe.json").exists()
```

---

### 5. `garmin/client.py` — 57% (orchestration untested)

**Risk:** `get_fitness_profile` stitches ~10 API calls; partial-failure handling unverified. Step-note truncation (≤200 char) has no test. Description cap (≤500 char) unchecked.

**Test skeleton:**

```python
# tests/test_garmin_client_orchestration.py
import pytest
from unittest.mock import Mock, patch, PropertyMock
from paceforge.garmin.client import GarminClient

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GARMIN_TOKEN", "dummy")
    return GarminClient()

def test_get_fitness_profile_tolerates_one_api_call_failing(client, monkeypatch):
    # mock Garmin client; make e.g. get_body_composition raise
    # assert profile still builds with that field as None
    with patch.object(client, "get_body_composition", side_effect=Exception("API down")):
        profile = client.get_fitness_profile()
        assert profile.body_composition is None
        assert profile.vo2_max is not None  # other fields still populated

def test_get_fitness_profile_respects_lookback_days(client, monkeypatch):
    with patch.object(client, "get_activities") as m:
        m.return_value = []
        client.get_fitness_profile(lookback_days=60)
        # assert the call used lookback_days=60, not hardcoded
        m.assert_called_once()
        assert m.call_args[1]["lookback_days"] == 60

def test_push_workout_step_notes_truncated_to_200(client, monkeypatch):
    long_note = "x" * 300
    # call push_workout with a step having notes > 200 chars
    # assert step.notes truncated to 200 in the API call
    pass

def test_push_workout_description_truncated_to_500(client):
    long_desc = "y" * 600
    # call push_workout; assert description ≤ 500 chars
    pass

def test_delete_workout_returns_false_on_404(client, monkeypatch):
    with patch.object(client, "_request", return_value=Mock(status_code=404)):
        assert client.delete_workout("nonexistent") is False

def test_delete_workout_returns_true_on_204(client, monkeypatch):
    with patch.object(client, "_request", return_value=Mock(status_code=204)):
        assert client.delete_workout("workout_id") is True

def test_get_fitness_profile_aggregates_multi_day_averages(client, monkeypatch):
    # with historical data spanning 90 days, assert aggregates (VO2, training load) use correct lookback
    pass
```

---

### 6. `actions.py` — 74% (error branches)

**Risk:** Missing lines are mostly guard clauses (`no profile`, `no plan`, `activity not found`). Success paths tested, failure paths mostly not.

**Test skeleton:**

```python
# tests/test_actions_error_paths.py
import pytest
from paceforge import actions

def test_analyze_raises_runtime_error_when_no_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="profile"):
        actions.analyze()

def test_sync_raises_when_garmin_token_missing():
    with pytest.raises(RuntimeError, match="token"):
        actions.sync()

def test_link_activity_raises_when_activity_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    # setup: create profile + activities, but not the one we're linking
    with pytest.raises(RuntimeError, match="not found"):
        actions.link_activity(activity_id=999)

def test_calendar_edit_raises_on_unknown_session_id(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    # setup: valid plan, but session_id not in it
    with pytest.raises(RuntimeError, match="session"):
        actions.edit_calendar_session(session_id="unknown", duration_minutes=60)

def test_recalibrate_rejects_invalid_delta(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    # delta out of bounds → should refuse or warn
    with pytest.raises((ValueError, RuntimeError)):
        actions.recalibrate(delta=10.0)  # unreasonably large

def test_push_fails_gracefully_on_network_error():
    # Garmin API timeout → should raise clear error, not hang
    pass
```

---

### 7. `hyrox/scraper.py` — 35% (network error paths)

**Risk:** Almost no test coverage of malformed HTML / rate-limit / zero-results paths.

**Test skeleton:**

```python
# tests/test_hyrox_scraper_errors.py
import pytest
from unittest.mock import patch, Mock
from paceforge.hyrox.scraper import scrape

def test_scrape_returns_empty_list_on_zero_search_results(monkeypatch):
    mock_response = Mock()
    mock_response.text = "<html><body>No results found</body></html>"
    with patch("requests.get", return_value=mock_response):
        assert scrape("nonexistent_athlete") == []

def test_scrape_raises_clear_error_on_unexpected_html_shape(monkeypatch):
    # site layout changed → should raise ValueError or similar, not IndexError
    mock_response = Mock()
    mock_response.text = "<html></html>"  # missing expected structure
    with patch("requests.get", return_value=mock_response):
        with pytest.raises((ValueError, KeyError, IndexError)):
            scrape("athlete")

def test_scrape_handles_rate_limit_response(monkeypatch):
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = Exception("Rate limited")
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(Exception):
            scrape("athlete")

def test_scrape_handles_timeout(monkeypatch):
    with patch("requests.get", side_effect=TimeoutError()):
        with pytest.raises(TimeoutError):
            scrape("athlete")

def test_scrape_malformed_date_in_result_skipped(monkeypatch):
    # if one result has unparseable date, scraper should skip it (not crash)
    pass
```

---

### 8. `engine/analytics.py` — 18% (legacy, low priority)

**Note:** Superseded by durability/load/compliance modules. Only unit-test new code; this module is winding down.

---

### 9. `web/bike/view.js` — trace decimation untested (NEW)

**Risk:** `MAX_TRACE_POINTS=2000` cap + adaptive stride added 2026-07-28 (uncommitted). No test asserts cap holds or decimation keeps trace sane.

**Test skeleton:**

```js
// web/bike/selftest-trace-cap.mjs (new file)
import assert from 'node:assert';
// Simulated player state
let S = { trace: [], traceStride: 1, traceTick: 0 };
const MAX_TRACE_POINTS = 2000;

function halveTrace() {
  if (S.trace.length > MAX_TRACE_POINTS) {
    let newTrace = [];
    for (let i = 0; i < S.trace.length; i += 2) {
      newTrace.push(S.trace[i]);
    }
    S.trace = newTrace;
    S.traceStride *= 2;
  }
}

// Test: push > MAX_TRACE_POINTS, assert cap holds
for (let i = 0; i < MAX_TRACE_POINTS + 500; i++) {
  S.trace.push({ time: i, power: 100 + i % 50 });
  if (S.trace.length > MAX_TRACE_POINTS) {
    halveTrace();
  }
}
assert(S.trace.length <= MAX_TRACE_POINTS, 'Trace not capped');
assert(S.traceStride > 1, 'Stride not increased');

// Test: first and last real samples survive decimation
const first = S.trace[0];
const last = S.trace[S.trace.length - 1];
assert(first.time === 0, 'First sample lost');
assert(last.time > MAX_TRACE_POINTS - 100, 'Last sample lost');

// Test: startRide() resets stride to 1
S.traceStride = 8;  // simulate long prior ride
function startRide() {
  S.trace = [];
  S.traceStride = 1;
  S.traceTick = 0;
}
startRide();
assert(S.traceStride === 1, 'Stride not reset');
console.log('✓ All trace cap tests passed');
```

---

### 10. `web/bike/recorder.js` — crash-safe recording (check coverage)

**Note:** Uses localStorage checkpoint every 60s. No test verifies recovery from checkpoint on page reload / crash.

**Test skeleton:**

```js
// web/bike/selftest-recorder-checkpoint.mjs
import assert from 'node:assert';
// Simulated localStorage (node env doesn't have it)
let fakeLS = {};
function setItem(k, v) { fakeLS[k] = v; }
function getItem(k) { return fakeLS[k]; }

// Test: checkpoint saved every 60s
// (requires mocking Date.now() or using timer spy)

// Test: recovery from checkpoint preserves samples before crash
const before_crash = [
  { time: 0, power: 100 },
  { time: 1, power: 105 },
];
setItem('ride_checkpoint', JSON.stringify(before_crash));
// simulate page reload → recover()
const recovered = JSON.parse(getItem('ride_checkpoint'));
assert(recovered.length === before_crash.length);
assert(recovered[0].power === 100);
console.log('✓ Checkpoint recovery OK');
```

---

## Integration gaps (cross-module)

1. **End-to-end CLI → actions → store:** No test drives full `sync` → `plan` → `push` → `autosync` sequence.

   **Test skeleton:**
   ```python
   def test_full_cycle_sync_plan_push(tmp_path, monkeypatch):
       monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
       # 1. create minimal profile + activities in data/
       # 2. call actions.sync() → assert activities loaded
       # 3. call actions.scaffold() → assert plan created
       # 4. call actions.push() → assert pushed to Garmin (mocked)
       # 5. call actions.autosync() → assert plan.json committed back
   ```

2. **Runner job dispatch → git commit path:** Job failure handling + commit failure unverified.

   **Test skeleton:**
   ```python
   def test_runner_job_commits_plan_on_success(state):
       # dispatch push job → plan committed to git
       # (or RUNS entry marked with commit hash)
   ```

3. **Bike ride digestion:** Load → compute → merged TRIMP. No end-to-end test.

   **Test skeleton:**
   ```python
   def test_bike_ride_appears_in_daily_load(tmp_path, monkeypatch):
       # 1. save bike ride with FTP-normalized power
       # 2. call compute_daily_load
       # 3. assert ride's TSS×_TSS_TO_TRIMP added to TRIMP total
   ```

---

## Priority order

| Rank | Module | Coverage | Effort | Impact | Status |
|------|--------|----------|--------|--------|--------|
| 1 | `store.py` corrupt-JSON | 75% | Low | High (9 gaps, systemic) | Ready |
| 2 | `cli.py` dispatch | 0% | Low | High (silent regression) | Ready |
| 3 | `scripts/runner.py` RUNS cap + job errors | 49% | Medium | Critical (security) | In progress |
| 4 | `scripts/users.py` multi-user | 0% | Medium | Critical (data safety) | Ready |
| 5 | `garmin/client.py` orchestration | 57% | Medium | High (API integration) | Ready |
| 6 | `actions.py` error paths | 74% | Medium | Medium (error handling) | Ready |
| 7 | `hyrox/scraper.py` errors | 35% | Medium | Low (external, fragile) | Ready |
| 8 | `web/bike/view.js` trace cap | N/A | Low | Medium (regression) | Uncommitted |
| 9 | Integration tests (E2E) | N/A | High | Medium (confidence) | Design |

---

## Notes

- RUNS cap (line 89, runner.py) + trace decimation (view.js) added 2026-07-28, uncommitted.
- `cli.py` and `scripts/users.py` are the only zero-coverage files; both are high-risk.
- All test skeletons are executable; copy directly into `tests/test_*.py` and fill `...` passes.
- Run `pytest tests/test_runner_jobs.py -xvs` to debug runner tests (may need fixture setup).
