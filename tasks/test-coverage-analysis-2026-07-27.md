# Test coverage analysis — 2026-07-27

465 tests pass, repo-wide 72% line coverage (`src/paceforge`). `scripts/runner.py`
(actively modified this session) sits at **48%** — lowest of any tested module and
carries the security-sensitive auth/Garmin-login code, so it's the focus below.
Coverage run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/ --cov=runner
--cov=paceforge --cov-report=term-missing`.

## Priority 1 — scripts/runner.py (48%, 325/631 lines missing)

Existing tests (`test_runner_auth.py`, `test_runner_dispatch.py`,
`test_runner_commit.py`, `test_runner_transforms.py`, `test_runner_coach_tools.py`)
cover: session auth gating, login/cookie flow, `dispatch()` failure/lock release,
`commit_push` pathspec scoping (no-remote case only), and the pure `save-*`
transforms. Gaps below, ordered by risk.

### 1. Garmin login flow — untested end to end (lines 202-306)

`garmin_login_start`, `garmin_mfa`, `_garmin_finish`, `_GarminProxy`. This is the
retry/rate-limit/MFA state machine behind a real credential handshake — zero
coverage. `GarminClient` is easy to stub (`monkeypatch.setattr(runner, ...)` won't
work since it's imported inside the function; patch
`paceforge.garmin.client.GarminClient` instead).

```python
# tests/test_runner_garmin_login.py
import sys, threading, time
from pathlib import Path
from unittest.mock import MagicMock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def garmin_state(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "GARMIN", {"status": "idle", "error": None,
                                            "detail": None, "email": None, "at": None})
    monkeypatch.setenv("PACEFORGE_GARMIN_TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "telegram", lambda *a, **k: None)
    monkeypatch.setattr(runner, "dispatch", lambda *a, **k: 0)


def _wait_status(target, timeout=2):
    for _ in range(int(timeout / 0.01)):
        if runner.GARMIN["status"] == target:
            return
        time.sleep(0.01)
    raise AssertionError(f"status never reached {target}, got {runner.GARMIN['status']}")


def test_login_success_updates_status_and_dispatches_sync(garmin_state, monkeypatch):
    client = MagicMock(login=MagicMock(return_value="ok"))
    monkeypatch.setattr("paceforge.garmin.client.GarminClient", lambda *a, **k: client)
    dispatched = []
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: dispatched.append(job))

    runner.garmin_login_start("a@b.com", "pw")
    _wait_status("ok")

    assert dispatched == ["sync"]


def test_login_mfa_required_sets_pending_status(garmin_state, monkeypatch):
    client = MagicMock(login=MagicMock(return_value="mfa_required"))
    monkeypatch.setattr("paceforge.garmin.client.GarminClient", lambda *a, **k: client)

    runner.garmin_login_start("a@b.com", "pw")
    _wait_status("pending_mfa")


def test_login_non_rate_limit_error_sets_status_error_immediately(garmin_state, monkeypatch):
    monkeypatch.setattr(runner, "RETRY_EVERY", 999)  # would hang the test if retried
    client = MagicMock(login=MagicMock(side_effect=RuntimeError("bad credentials")))
    monkeypatch.setattr("paceforge.garmin.client.GarminClient", lambda *a, **k: client)

    runner.garmin_login_start("a@b.com", "pw")
    _wait_status("error")
    assert "bad credentials" in runner.GARMIN["error"]


def test_login_rate_limit_retries_then_gives_up(garmin_state, monkeypatch):
    monkeypatch.setattr(runner, "RETRY_EVERY", 0)
    monkeypatch.setattr(runner, "MAX_ATTEMPTS", 2)
    client = MagicMock(login=MagicMock(side_effect=RuntimeError("429 Too Many Requests")))
    monkeypatch.setattr("paceforge.garmin.client.GarminClient", lambda *a, **k: client)

    runner.garmin_login_start("a@b.com", "pw")
    _wait_status("error", timeout=2)
    assert "rate-limited" in runner.GARMIN["error"]


def test_stale_token_file_is_renamed_before_login(garmin_state, monkeypatch, tmp_path):
    (tmp_path / "garmin_tokens.json").write_text("stale")
    client = MagicMock(login=MagicMock(return_value="ok"))
    monkeypatch.setattr("paceforge.garmin.client.GarminClient", lambda *a, **k: client)

    runner.garmin_login_start("a@b.com", "pw")
    _wait_status("ok")
    assert (tmp_path / "garmin_tokens.json.stale").exists()


def test_mfa_without_prior_login_sets_error(garmin_state, monkeypatch):
    monkeypatch.setattr(runner, "_GARMIN_CLIENT", None)
    runner.garmin_mfa("123456")
    _wait_status("error")
    assert "no login in progress" in runner.GARMIN["error"]


def test_garmin_proxy_sets_and_restores_env(monkeypatch):
    monkeypatch.setattr(runner, "GARMIN_PROXY", "socks5://127.0.0.1:40000")
    monkeypatch.delenv("https_proxy", raising=False)
    with runner._GarminProxy():
        assert os.environ["https_proxy"] == "socks5://127.0.0.1:40000"
    assert "https_proxy" not in os.environ
```

### 2. `telegram()` — completely untested (lines 166-187)

No-op without env, HTML-escape + truncation, plain-text fallback resend on
send failure.

```python
# tests/test_runner_telegram.py
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


def test_telegram_noops_without_token(monkeypatch):
    monkeypatch.delenv("TG_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    calls = []
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *a, **k: calls.append(1))
    runner.telegram("hi")
    assert calls == []


def test_telegram_html_escapes_plain_text(monkeypatch):
    monkeypatch.setenv("TG_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "c")
    sent = {}
    def fake_urlopen(req, timeout=30):
        sent["data"] = req.data
        class R:
            def read(self): return b'{"ok":true}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    runner.telegram("<script>")
    assert b"%3Cscript%3E" not in sent["data"] and b"&lt;script&gt;" in sent["data"]


def test_telegram_falls_back_to_plain_on_html_rejection(monkeypatch):
    monkeypatch.setenv("TG_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "c")
    calls = []
    def fake_urlopen(req, timeout=30):
        calls.append(req.data)
        class R:
            def read(self): return b'{"ok":false}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    runner.telegram("body", html=True, title="T")
    assert len(calls) == 2  # first attempt + plain resend
```

### 3. `commit_push` — forgejo fallback path untested (lines 148-151)

Existing tests only cover the no-remote branch. Need: `origin` present but push
fails → falls back to `forgejo` push.

```python
def test_origin_push_failure_falls_back_to_forgejo(repo, run, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "sh", lambda run, cmd, **k: (
        calls.append(cmd), 1 if cmd[:3] == ["git", "push", "origin"] else 0)[1])
    (repo / "data" / "plan.json").write_text('{"weeks": 1}')

    runner.commit_push(run, ["data/"], "data: sync")

    assert ["git", "push", "forgejo"] in calls
```

### 4. `reconcile_garmin()` — completely untested (lines 433-456)

Non-fatal-on-failure Garmin autosync wrapper called after every plan-mutating job.
Covers: success → commit + Telegram counts; `autosync` non-zero exit → Telegram
failure, job continues (doesn't raise).

```python
def test_reconcile_garmin_failure_is_non_fatal_and_telegrams(run, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="boom\n"))
    alerts = []
    monkeypatch.setattr(runner, "telegram", lambda t, *a, **k: alerts.append(t))
    monkeypatch.setattr(runner, "commit_push", lambda *a, **k: pytest.fail("must not commit"))

    runner.reconcile_garmin(run)  # must not raise

    assert "Garmin reconcile failed" in alerts[0]


def test_reconcile_garmin_success_telegrams_counts(run, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"pushed": 2, "stale_deleted": 1, "orphans_deleted": 0, "failed": []}',
        stderr=""))
    monkeypatch.setattr(runner, "commit_push", lambda *a, **k: None)
    alerts = []
    monkeypatch.setattr(runner, "telegram", lambda t, *a, **k: alerts.append(t))

    runner.reconcile_garmin(run)

    assert "2 pushed" in alerts[0]
```

### 5. Job orchestration functions — near-zero coverage

`job_sync`, `job_daily`, `job_analyze`, `job_plan`, `job_push`, `job_autosync`,
`job_recalibrate`, `job_calendar_edit`, `job_garmin_delete`,
`job_garmin_clear_calendar`, `job_hyrox` are only exercised via `dispatch()` with a
fake `_boom` job in `test_runner_dispatch.py` — the real bodies never run. Each
wires `sh`/`pf`/`commit_push`/`publish`/`telegram`/`reconcile_garmin` — the
branches worth locking down:

- `job_sync`: morning-hour branch dispatches `brief --telegram` + `daily`;
  non-morning branch skips both; `rc != 0` telegrams + raises (job marked failed)
  but still dispatches `analyze` first only on... actually check ordering — raise
  happens *before* `dispatch("analyze")`, so a failed sync must NOT analyze.
- `job_plan`: `mode == "reassess"` runs `adapt` instead of `plan`; `mode ==
  "create"` sets `accepted: true` on the scaffold and runs the AI-enrichment
  `claude_step`, catching (not re-raising) its exceptions.
- `job_push` / `job_recalibrate` / `job_calendar_edit`: optional-input flag
  plumbing (`--week`, `--dry-run`, `--new-date`) reaching the `pf()` argv.
- `job_garmin_clear_calendar`: `dry_run` default true skips the commit entirely.

```python
# tests/test_runner_jobs.py
import sys, json
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402


@pytest.fixture
def run():
    return SimpleNamespace(step=lambda *a: None, log=lambda *a: None)


@pytest.fixture
def stub_job_io(monkeypatch):
    calls = {"sh": [], "commit_push": [], "telegram": []}
    monkeypatch.setattr(runner, "sh", lambda run, cmd, **k: (calls["sh"].append(cmd), 0)[1])
    monkeypatch.setattr(runner, "commit_push", lambda run, paths, msg: calls["commit_push"].append((paths, msg)))
    monkeypatch.setattr(runner, "publish", lambda *a, **k: None)
    monkeypatch.setattr(runner, "telegram", lambda t, *a, **k: calls["telegram"].append(t))
    monkeypatch.setattr(runner, "reconcile_garmin", lambda *a, **k: None)
    return calls


def test_job_sync_failure_does_not_dispatch_analyze(run, stub_job_io, monkeypatch):
    monkeypatch.setattr(runner, "sh", lambda run, cmd, **k: (
        stub_job_io["sh"].append(cmd), 1 if cmd[-1] == "sync" else 0)[1])
    dispatched = []
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: dispatched.append(job))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="", stderr=""))

    with pytest.raises(RuntimeError):
        runner.job_sync(run, {})

    assert "analyze" not in dispatched


def test_job_plan_reassess_mode_calls_adapt_not_plan(run, stub_job_io, monkeypatch):
    monkeypatch.setattr(runner, "claude_step", lambda *a, **k: None)
    monkeypatch.setattr(Path, "read_text", lambda self: "{}")
    monkeypatch.setattr(Path, "write_text", lambda self, s: None)

    runner.job_plan(run, {"mode": "reassess"})

    argv_tails = [c[-1] for c in stub_job_io["sh"] if c and c[0].endswith("paceforge")]
    assert "adapt" in argv_tails and "plan" not in [a.split()[0] for a in argv_tails if False] or True
    # simpler: assert the pf() argv list containing "adapt" was passed to sh
    assert any(cmd[1] == "adapt" for cmd in stub_job_io["sh"] if len(cmd) > 1)


def test_job_plan_create_mode_enrichment_failure_is_swallowed(run, stub_job_io, monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda self: "{}")
    monkeypatch.setattr(Path, "write_text", lambda self, s: None)
    monkeypatch.setattr(runner, "claude_step", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("turns exhausted")))

    runner.job_plan(run, {"mode": "create", "event_type": "HYROX", "target_date": "2026-10-04"})
    # must not raise — enrichment failure is non-fatal


def test_job_garmin_clear_calendar_dry_run_skips_commit(run, stub_job_io):
    runner.job_garmin_clear_calendar(run, {})

    assert stub_job_io["commit_push"] == []


def test_job_push_passes_week_and_dry_run_flags(run, stub_job_io):
    runner.job_push(run, {"week": 3, "dry_run": "true"})

    argv = stub_job_io["sh"][0]
    assert "--week" in argv and "3" in argv and "--dry-run" in argv
```

### 6. `_save_job()` wrapper — only the inner `transform` is tested (lines 682-691)

The wrapper itself (string-vs-dict `data`, commit message, `publish()` call) is
never exercised as a job.

```python
def test_save_job_parses_json_string_payload(run, stub_job_io, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    (tmp_path / "data").mkdir()
    job = runner.JOBS["save-rpe"]

    job(run, {"data": json.dumps({"activity_id": 1, "date": "2026-07-27", "rpe": 6})})

    assert json.loads((tmp_path / "data" / "rpe.json").read_text())["entries"][0]["rpe"] == 6
```

### 7. Session persistence — untested (lines 749-761)

`_load_sessions()` (restore across restart) and the prune-expired branch inside
`_new_session()`.

```python
def test_load_sessions_restores_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runner, "_SESSIONS", {})
    (tmp_path / "sessions.json").write_text('{"tok123": 1234567890.0}')

    runner._load_sessions()

    assert runner._SESSIONS["tok123"] == 1234567890.0


def test_new_session_prunes_expired_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runner, "_SESSIONS", {"old": time.time() - runner.SESSION_TTL - 1})

    runner._new_session()

    assert "old" not in runner._SESSIONS
```

### 8. HTTP routes with zero coverage — GET

`/` and `/index.html` (static serve success), `/data/<path>`, `/garmin/status`,
`/auth/whoami`, `/runs/<id>/log`, `/gh/repos/.../actions/workflows/<wf>/runs`,
`/gh/repos/.../actions/runs/<id>/jobs`, `/gh/repos/.../contents/<path>` **success**
case (only path-traversal is tested), `/gh/repos/.../issues` (empty list),
`/gh/repos/<o>/<r>` (repo info), and `_static()`'s success branch generally.

```python
# add to tests/test_runner_auth.py (reuses the `app` fixture)
def test_authed_root_serves_portal_html(app):
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/", headers={"Cookie": cookie})
    assert code == 200 and b"<html" in body.lower()


def test_whoami_returns_configured_user(app, monkeypatch):
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/api/auth/whoami", headers={"Cookie": cookie})
    assert json.loads(body)["user"] == "victor"


def test_contents_route_returns_base64_for_real_data_file(app, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "plan.json").write_text("hello")
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/api/gh/repos/o/r/contents/data/plan.json",
                          headers={"Cookie": cookie})
    assert json.loads(body)["encoding"] == "base64"


def test_run_log_route_returns_no_log_placeholder_when_missing(app):
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/api/gh/runs/999999/log", headers={"Cookie": cookie})
    assert body == b"no log"
```

### 9. HTTP routes with zero coverage — POST

`/garmin/login` (missing email/password → 400; valid → 202 + starts login),
`/garmin/mfa` (missing code → 400), `/run/<job>` dispatch, `/gh/.../dispatches`
(unknown job → 404), `/gh/.../issues` (creates a `coach` run from title+body).

```python
def test_garmin_login_requires_password(app):
    cookie = _session_cookie(app)
    code, _, _ = _req(app.public + "/api/garmin/login", "POST", {"email": "a@b.com"},
                       {"Cookie": cookie})
    assert code == 400


def test_run_route_dispatches_known_job(app, monkeypatch):
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: 42)
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/api/run/sync", "POST", {}, {"Cookie": cookie})
    assert code == 200 and json.loads(body)["id"] == 42


def test_workflow_dispatch_route_rejects_unknown_job(app):
    cookie = _session_cookie(app)
    code, _, _ = _req(
        app.public + "/api/gh/repos/o/r/actions/workflows/nonsense/dispatches",
        "POST", {"inputs": {}}, {"Cookie": cookie})
    assert code == 404


def test_issues_route_creates_coach_run_from_title_and_body(app, monkeypatch):
    monkeypatch.setattr(runner, "dispatch", lambda job, inputs: 7)
    cookie = _session_cookie(app)
    code, _, body = _req(app.public + "/api/gh/repos/o/r/issues", "POST",
                          {"title": "Review week", "body": "details"}, {"Cookie": cookie})
    assert code == 201 and json.loads(body)["number"] == 7
```

## Priority 2 — other modules (summary only; not actively touched this session)

| Module | Coverage | Main gap |
|---|---|---|
| `cli.py` | 0% | Whole argparse entrypoint untested — no test invokes `main()` at all. Skeleton: `runner.main(["sync", "--lookback-days", "5"])` style, mocking `actions.*`, assert correct action called with parsed args. |
| `garmin/client.py` | 57% | Retry/backoff, MFA completion, workout-upload error paths (lines 203-262, 387-523, 648-741 etc.) — mostly network-error branches needing a fake `garminconnect` client. |
| `hyrox/scraper.py` | 35% | HTML-parsing edge cases and network fetch failures (lines 85-273, 427-541) — needs fixture HTML pages, not live scraping. |
| `analytics.py` | 18% | Legacy module per CLAUDE.md ("LEGACY snapshot analysis") — low priority; confirm nothing new depends on it before investing here. |
| `hyrox/hyresult.py` | 70% | Result-parsing edge cases (missing splits, malformed times) — lines 45-101. |
| `store.py` | 76% | Corrupt-JSON fallback branches across every `load_*()` (lines 143-163, 194-248) — same pattern repeated; one parametrized test could cover most: write invalid JSON, assert the documented empty-default return instead of a raised exception. |
| `actions.py` | 74% | Error paths around Garmin auth failures and edge-case CLI flag combos (lines 594-702 is the biggest single block — worth a dedicated look before the next actions.py change). |

## Integration gaps (cross-cutting)

- No test exercises `main()`'s startup sequence (session/run-id resume from disk,
  dual-port bind) — reasonable to leave as an untested integration path given it's
  systemd-managed, but a quick smoke test for the run-id resume logic (extract it
  from `main()` into a small pure function if it grows) would catch corruption of
  `runs.jsonl`.
- No test verifies a `job_plan` → `reconcile_garmin` → Telegram round trip end to
  end (each piece is unit-tested individually per above, but never chained).
- No test covers two jobs racing on `JOB_LOCK` for real concurrent throughput
  (only the release-after-failure case is tested).
