# Test coverage gaps — 2026-07-27

Measured, not guessed: `pytest --cov=src/paceforge` → **72%** (469 passed).
`pytest --cov=scripts` → **34%** (runner.py alone: 49%).

## Worst offenders (stmts, cover)

| File | Cover | Note |
|---|---|---|
| `cli.py` | 0% | argparse dispatch, zero tests, any regression here ships silently |
| `engine/analytics.py` | 18% | legacy module, low priority (superseded by durability/load/etc) |
| `hyrox/scraper.py` | 35% | network scraping, untested parse/error paths |
| `scripts/users.py` | 0% | multi-user provisioning (clone/env/Caddy route) — no tests at all |
| `scripts/runner.py` | 49% | **security-critical**: auth, job dispatch, HTTP handling |
| `garmin/client.py` | 57% | `get_fitness_profile` (465 lines) orchestration untested, only leaf parsers are |
| `hyrox/hyresult.py` | 70% | |
| `actions.py` | 74% | core action layer, error branches untested |
| `store.py` | 75% | every `load_*` has an untested corrupt-JSON fallback branch |

## 1. `cli.py` — 0% covered

Thin dispatcher (`args.cmd == "..."` → `actions.X()` → `_emit`), but a broken subcommand
wiring (wrong kwarg, missing `elif`) ships undetected. No integration test exercises
`main()` end-to-end.

```python
# tests/test_cli.py
from unittest.mock import patch
from paceforge.cli import main

def test_status_dispatches_to_actions_status(capsys):
    with patch("paceforge.actions.status", return_value={"ok": True}) as m:
        assert main(["status"]) == 0
    m.assert_called_once_with()
    assert '"ok": true' in capsys.readouterr().out

def test_plan_builds_scaffold_dict_from_args():
    with patch("paceforge.actions.scaffold", return_value={}) as m:
        main(["plan", "--goal", "MARATHON", "--date", "2026-10-04"])
    kwargs = m.call_args[0][0]
    assert kwargs["goal_type"] == "MARATHON"
    assert kwargs["training_days"] == ["tuesday", "thursday", "saturday", "sunday"]

def test_validate_returns_exit_1_on_issues(capsys):
    with patch("paceforge.actions.validate", return_value=["pace out of order"]):
        assert main(["validate"]) == 1
    assert "INVALID" in capsys.readouterr().out

def test_runtime_error_prints_to_stderr_and_exits_1(capsys):
    with patch("paceforge.actions.status", side_effect=RuntimeError("no profile")):
        assert main(["status"]) == 1
    assert "error: no profile" in capsys.readouterr().err
```

## 2. `scripts/users.py` — 0% covered

Provisions a friend's isolated instance: clone, env file (scrypt hash), systemd unit,
Caddy route. No test → a bug here corrupts someone else's install, or leaks a
password in a git-tracked file.

```python
# tests/test_users.py
def test_add_writes_scrypt_hash_not_plaintext_password(tmp_path, monkeypatch):
    # arrange: point instance root at tmp_path, run add("alice")
    # assert: env file contains PF_WEB_PASS_SCRYPT=<salt>$<hash>, never the raw password
    ...

def test_add_is_idempotent_when_instance_already_exists(tmp_path):
    # calling add("alice") twice must not clobber alice's existing data/ or token dir
    ...

def test_remove_requires_explicit_yes_flag():
    # remove("alice") without --yes must refuse (destructive op guard)
    ...

def test_update_copies_web_scripts_ops_but_not_data(tmp_path):
    # scripts/users.py update must not drag Victor's data/*.json into the instance
    ...
```

## 3. `scripts/runner.py` — 49% (security-critical, per earlier audit)

Existing tests (`test_runner_auth.py`, `test_runner_dispatch.py`, ...) cover the happy
paths. Missing lines cluster around job-execution error handling and the HTTP
server's request lifecycle (`495-561`, `604-679`).

```python
# tests/test_runner_jobs.py
def test_job_failure_is_recorded_in_runs_list_with_traceback():
    # dispatch a job whose handler raises; assert RUNS[-1]["status"] == "error"
    # and RUNS[-1]["error"] contains the exception message (not swallowed silently)
    ...

def test_concurrent_job_dispatch_is_serialized_by_lock():
    # two dispatches to the same job racing must not corrupt plan.json
    # (thread lock around the job → data/plan.json write path)
    ...

def test_runs_list_is_capped_and_does_not_grow_unbounded():
    # append > cap jobs, assert len(RUNS) stays bounded (memory-leak regression per obs 7753)
    ...

def test_malformed_request_body_returns_400_not_500():
    # POST with invalid JSON to a job endpoint → 400, not an unhandled exception
    ...
```

## 4. `garmin/client.py` — 57%, `get_fitness_profile` orchestration untested

`test_garmin_profile.py` only unit-tests leaf parsers (sleep score, VO2, body battery).
The outer function that stitches ~10 API calls together — partial-failure handling,
missing-field defaults — is not exercised as a whole.

```python
# tests/test_garmin_profile_orchestration.py
def test_get_fitness_profile_tolerates_one_api_call_failing(monkeypatch):
    # mock Garmin client so e.g. get_body_composition raises; assert profile still
    # builds with that field as None, rather than the whole sync aborting
    ...

def test_get_fitness_profile_respects_lookback_days_window():
    # assert the activity-fetch call uses the given lookback_days, not a hardcoded value
    ...

def test_delete_workout_returns_false_on_404_not_raise():
    ...

def test_push_workout_step_notes_truncated_to_200_chars():
    # per CLAUDE.md: per-step notes ≤200 chars, description ≤500 — no test asserts the cap
    ...
```

## 5. `store.py` — every loader's corrupt-JSON branch is untested

Systemic gap, same shape repeated ~9 times (`load_rpe`, `load_token_meta`,
`load_sync_status`, `load_all_details`, `load_hyrox_results`, `load_hyrox_analysis`,
`load_benchmarks`, `load_events`, `load_history`): all catch
`(json.JSONDecodeError, OSError)` and fall back to an empty default, but no test
writes a truncated/corrupt file and checks the fallback fires instead of crashing
the sync job.

```python
# tests/test_store_corrupt_files.py
import pytest

@pytest.mark.parametrize("loader,path,default", [
    ("load_rpe", "rpe.json", {"entries": []}),
    ("load_token_meta", "token-meta.json", None),
    ("load_sync_status", "sync-status.json", None),
    ("load_hyrox_results", "hyrox.json", []),
    ("load_events", "events.json", []),
])
def test_corrupt_json_falls_back_to_default(tmp_path, monkeypatch, loader, path, default):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    (tmp_path / path).write_text("{not valid json")
    from paceforge import store
    assert getattr(store, loader)() == default

def test_load_all_details_skips_one_corrupt_file_keeps_others(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    d = tmp_path / "details"; d.mkdir()
    (d / "1.json").write_text('{"activity_id": 1}')
    (d / "2.json").write_text("garbage")
    from paceforge import store
    assert store.load_all_details() == {1: {"activity_id": 1}}
```

## 6. `hyrox/scraper.py` — 35%

Network scraping with almost no test coverage of malformed-HTML / rate-limit /
zero-results paths.

```python
# tests/test_hyrox_scraper_errors.py
def test_scrape_returns_empty_list_on_zero_search_results(mock_response):
    ...

def test_scrape_raises_clear_error_on_unexpected_html_shape(mock_response):
    # site layout changed → should raise something actionable, not IndexError/KeyError
    ...

def test_scrape_handles_rate_limit_response(mock_response):
    ...
```

## 7. `actions.py` — 74%, error branches in the big functions

Missing lines are mostly `RuntimeError`/`KeyError` guard clauses (e.g. no profile,
no plan, activity not found) — the success paths are well tested, the failure
paths mostly aren't.

```python
# tests/test_actions_error_paths.py
def test_analyze_raises_runtime_error_when_no_profile_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("PACEFORGE_DATA_DIR", str(tmp_path))
    from paceforge import actions
    with pytest.raises(RuntimeError, match="profile"):
        actions.analyze()

def test_link_activity_raises_when_activity_id_not_found():
    ...

def test_calendar_edit_raises_on_unknown_session_id():
    ...
```

## 8. `web/bike/view.js` — `MAX_TRACE_POINTS` cap added, untested (uncommitted 2026-07-28)

`RUNS[:-200]` cap in `runner.py:89` closes gap #3's test target. `view.js` got the
same shape fix for the power-trace polyline (`S.trace`) — no test asserts the
2000-point cap actually holds or that decimation keeps the trace visually sane.

```js
// web/bike/selftest-trace-cap.mjs
import assert from 'node:assert';
// simulate MAX_TRACE_POINTS + 500 pushes to S.trace via the same push/decimate path
// assert trace.length <= MAX_TRACE_POINTS
// assert first and last real samples survive decimation (not just truncated off the end)
```

## Integration gaps (cross-module, not just missing unit tests)

- No test drives `cli.main()` → `actions.*` → `store.*` end-to-end against a real
  tmp `data/` dir for a full `sync` → `plan` → `push` → `autosync` sequence.
- No test exercises the runner's job dispatch → `actions.*` → git commit-back path
  (`push`/`autosync` commit `plan.json`) — commit failure handling is unverified.
- Bike ride digestion (`load_bike_rides` → `compute_daily_load`) has unit coverage
  per file but no test asserts a bike ride actually shows up in
  `compute_load_recovery`'s combined TRIMP total end-to-end.

## New since 2026-07-27 (uncommitted as of 2026-07-28 03:08 UTC) — zero test coverage

### `scripts/runner.py` — `RUNS` memory cap (`del RUNS[:-200]`, line 89)

```python
# tests/test_runner_jobs.py (append)
def test_runs_list_is_capped_at_200(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "noop", lambda run: None)
    for _ in range(210):
        _run_to_completion("noop")
    assert len(runner.RUNS) == 200

def test_runs_cap_keeps_most_recent(state, alerts, monkeypatch):
    monkeypatch.setitem(runner.JOBS, "noop", lambda run: None)
    for _ in range(210):
        _run_to_completion("noop")
    assert runner.RUNS[-1]["id"] == max(r["id"] for r in runner.RUNS)
    assert runner.RUNS[0]["id"] not in (0, 1)  # oldest ids evicted
```

### `web/bike/view.js` — trace decimation (`MAX_TRACE_POINTS`, `traceStride`, `updatePlayer`)

No Node selftest covers this (existing selftests are `selftest-ble.mjs`, `selftest-fit.mjs`,
`selftest-formats.mjs` — none touch the player/trace). Needs a new one, or export
`updatePlayer`'s trace logic for direct testing (currently a module-private closure over `S`).

```js
// web/bike/selftest-trace.mjs (new file)
// Feed > MAX_TRACE_POINTS synthetic snapshots through updatePlayer and assert:
// 1. S.trace.length never exceeds MAX_TRACE_POINTS after the halving pass
// 2. S.traceStride doubles exactly when the halving triggers (1 -> 2 -> 4 ...)
// 3. startRide() resets traceStride to 1 and traceTick to 0 for a fresh ride
//    (regression: a stride carried over from a previous long ride would
//    under-sample the start of the next one)
```

## Priority order

1. `store.py` corrupt-JSON parametrized test (cheap, closes 9 gaps at once)
2. `cli.py` dispatch tests (cheap, catches wiring regressions)
3. `scripts/runner.py` job-failure + RUNS-cap tests (security/reliability critical)
4. `scripts/users.py` (currently *zero* tests on code that touches other people's data)
5. `garmin/client.py` orchestration + truncation tests
6. `hyrox/scraper.py` error paths (lower priority, external site dependency)
