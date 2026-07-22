"""Local job runner — replaces GitHub Actions while the account is flagged (ticket 4583559).

The portal (web/index.html + web/bike/view.js) talks to `GH_API`, which is
`https://api.github.com` on GitHub Pages and `api/gh` when served off the VM.
This runner speaks the minimal GitHub-API subset the portal actually uses, so
the frontend needed only a base-URL swap and the Pages path stays intact as
rollback:

    POST /run/<job>                                        systemd timers / curl
    GET  /runs                                             recent runs (debug)
    GET  /runs/<id>/log                                    plain-text run log
    POST /gh/repos/<o>/<r>/actions/workflows/<wf>/dispatches
    GET  /gh/repos/<o>/<r>/actions/workflows/<wf>/runs
    GET  /gh/repos/<o>/<r>/actions/runs/<id>/jobs
    POST /gh/repos/<o>/<r>/issues                          coach request
    GET  /gh/repos/<o>/<r>/issues                          [] (nothing pending)
    GET  /gh/repos/<o>/<r>/contents/data/<path>            analysis polling
    GET  /gh/repos/<o>/<r>                                 token "test" → 200
    GET  /healthz

Binds 127.0.0.1 only; Caddy fronts it at /paceforge/api/* with basic_auth.
Jobs mirror .github/workflows/*.yml step-for-step (same commands, same commit
paths, same messages); the two claude-code-action steps run the local `claude`
CLI instead. Every job holds one global lock — the workflows'
`concurrency: group: paceforge-data` — because concurrent data/ writes corrupt
the JSON. After any data change the site is republished to /srv/paceforge
(build_site_data.py + rsync), which replaces pages.yml.

Usage:  python scripts/runner.py            # serve (systemd: paceforge-runner)
        python scripts/runner.py --publish  # one-shot build + rsync to /srv
"""

from __future__ import annotations

# ruff: noqa: S603, S607, S310  (fixed argv lists; https-only Telegram URL)
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
VENV_BIN = REPO_DIR / ".venv" / "bin"
STATE_DIR = Path(os.environ.get("PACEFORGE_RUNNER_STATE", Path.home() / ".local/state/paceforge-runner"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local/bin/claude"))
PORT = int(os.environ.get("PACEFORGE_RUNNER_PORT", "8123"))
BOT = ["-c", "user.name=paceforge-bot", "-c", "user.email=bot@paceforge.local"]

JOB_LOCK = threading.Lock()   # ponytail: one global lock = the workflows' paceforge-data group
RUNS_LOCK = threading.Lock()
RUNS: list[dict] = []
_NEXT_ID = 1


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── run records (GitHub Actions "runs" vocabulary, so the portal maps 1:1) ──

class Run:
    def __init__(self, name: str):
        global _NEXT_ID
        with RUNS_LOCK:
            self.id = _NEXT_ID
            _NEXT_ID += 1
            self.rec = {
                "id": self.id, "name": name, "status": "queued", "conclusion": None,
                "created_at": now(), "run_started_at": None, "steps": [],
            }
            RUNS.append(self.rec)
        self.log_path = STATE_DIR / f"run-{self.id}-{name}.log"

    def log(self, text: str) -> None:
        with open(self.log_path, "a") as f:
            f.write(text.rstrip() + "\n")

    def step(self, name: str) -> None:
        self._close_step("success")
        self.rec["steps"].append({"name": name, "status": "in_progress", "conclusion": None})
        self.log(f"\n── {name} ──")

    def _close_step(self, conclusion: str) -> None:
        if self.rec["steps"] and self.rec["steps"][-1]["status"] != "completed":
            self.rec["steps"][-1].update(status="completed", conclusion=conclusion)

    def finish(self, ok: bool) -> None:
        self._close_step("success" if ok else "failure")
        self.rec.update(status="completed", conclusion="success" if ok else "failure")
        with open(STATE_DIR / "runs.jsonl", "a") as f:
            f.write(json.dumps(self.rec) + "\n")


def sh(run: Run, cmd: list[str], check: bool = True, timeout: int = 900, env: dict | None = None) -> int:
    run.log("$ " + " ".join(cmd))
    p = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, **(env or {})})
    if p.stdout:
        run.log(p.stdout)
    if p.stderr:
        run.log(p.stderr)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} exited {p.returncode}")
    return p.returncode


def pf(*args: str) -> list[str]:
    return [str(VENV_BIN / "paceforge"), *args]


def commit_push(run: Run, paths: list[str], msg: str) -> None:
    sh(run, ["git", "add", *paths])
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR).returncode == 0:
        run.log("nothing to commit")
        return
    sh(run, ["git", *BOT, "commit", "-m", msg])
    # GitHub first (Victor's token works); Forgejo fallback — the relay reconciles.
    if sh(run, ["git", "push", "origin"], check=False) != 0:
        run.log("origin push failed — pushing forgejo (relay will reconcile)")
        sh(run, ["git", "push", "forgejo"])


def publish(run: Run | None = None) -> None:
    """pages.yml replacement: bake derived JSON. The runner serves web/ + data/
    straight from the repo, so there is nothing to copy anywhere."""
    def _log(t: str) -> None:
        run.log(t) if run else print(t)
    p = subprocess.run([str(VENV_BIN / "python"), "scripts/build_site_data.py"],
                       cwd=REPO_DIR, capture_output=True, text=True, timeout=300)
    _log(p.stdout + p.stderr)
    if p.returncode != 0:
        raise RuntimeError("build_site_data.py failed")


def telegram(text: str, pre: bool = False, title: str = "") -> None:
    tok, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        return
    api = f"https://api.telegram.org/bot{tok}/sendMessage"
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:3900]
    html = f"<b>{title}</b>\n<pre>{esc}</pre>" if pre else esc

    def send(body: dict) -> bool:
        data = urllib.parse.urlencode(body).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(api, data=data), timeout=30) as r:
                return b'"ok":true' in r.read()
        except Exception:
            return False
    # HTML-rejection must not drop the message: resend plain (ported from sync.yml).
    if not send({"chat_id": chat, "text": html, "parse_mode": "HTML", "disable_web_page_preview": "true"}):
        send({"chat_id": chat, "text": f"{title}\n{text}"[:3900], "disable_web_page_preview": "true"})


def claude_step(run: Run, prompt: str, tools: str, max_turns: int = 200,
                env: dict | None = None, timeout: int = 2700) -> None:
    sh(run, [CLAUDE_BIN, "-p", prompt, "--max-turns", str(max_turns),
             "--allowedTools", tools, "--output-format", "text"],
       timeout=timeout, env=env)


# ── Garmin login, portal-driven (`paceforge login` needs a TTY; the portal
# posts password → optional MFA code instead). Credentials live only in this
# process for the duration of the handshake — never logged, never persisted;
# only the resulting token lands in the token dir, same as the CLI. ──

GARMIN = {"status": "idle", "error": None, "detail": None, "email": None, "at": None}
_GARMIN_CLIENT = None


def _garmin_finish() -> None:
    from paceforge import store
    store.save_token_meta({"login_date": datetime.now(UTC).date().isoformat()})
    GARMIN.update(status="ok", error=None, at=now())
    dispatch("sync", {})   # verify the token + backfill immediately


RETRY_EVERY = 45 * 60
MAX_ATTEMPTS = 10
# Garmin rate-limits per IP and this VM's IP burns fast; the handshake goes out
# through Cloudflare WARP (socks5 on localhost) for a clean egress identity.
GARMIN_PROXY = os.environ.get("PF_GARMIN_PROXY", "")


class _GarminProxy:
    """Route the Garmin handshake through PF_GARMIN_PROXY via proxy env vars.
    ponytail: process-global env for the login window — a job that fires
    mid-handshake would also ride the proxy, which is harmless."""

    KEYS = ("https_proxy", "http_proxy", "all_proxy")

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.KEYS}
        if GARMIN_PROXY:
            for k in self.KEYS:
                os.environ[k] = GARMIN_PROXY
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        return False


def garmin_login_start(email: str, password: str) -> None:
    """One credential entry, then the runner outlasts Garmin's per-IP 429 by
    itself: retry every 45 min, Telegram when it connects or needs MFA."""
    GARMIN.update(status="authenticating", error=None, detail=None, email=email, at=now())

    def work() -> None:
        global _GARMIN_CLIENT
        from paceforge.garmin.client import GarminClient
        td = Path(os.environ.get("PACEFORGE_GARMIN_TOKEN_DIR",
                                 Path.home() / ".garminconnect"))
        td.mkdir(parents=True, exist_ok=True)
        # A stale tokenstore short-circuits the library's credential login
        # (it loads the dead token, skips the password entirely, then dies
        # on the first API call) — move it aside so this login is real.
        for f in td.glob("garmin_tokens.json"):
            f.replace(f.with_name(f.name + ".stale"))
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                client = GarminClient(email, password, token_dir=str(td))
                _GARMIN_CLIENT = client
                with _GarminProxy():
                    result = client.login()
                if result == "mfa_required":
                    GARMIN.update(status="pending_mfa", error=None, detail=None, at=now())
                    telegram("🏃 PaceForge: Garmin sign-in needs your MFA code — "
                             "portal → Settings → Connect Garmin.")
                else:
                    # return_on_mfa mode returns before the library persists
                    # the tokens — dump them the same way complete_mfa() does.
                    client._client.client.dump(str(td))  # noqa: SLF001
                    _garmin_finish()
                    telegram("🏃 PaceForge: Garmin connected — full sync is running.")
                return
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                if "429" not in msg and "rate limit" not in msg.lower():
                    GARMIN.update(status="error", error=msg, detail=None, at=now())
                    telegram(f"🏃 PaceForge: Garmin sign-in failed — {msg}")
                    return
                nxt = datetime.now(UTC).timestamp() + RETRY_EVERY
                GARMIN.update(status="waiting_retry", error=msg, at=now(),
                              detail=f"attempt {attempt}/{MAX_ATTEMPTS}, next retry "
                                     f"{datetime.fromtimestamp(nxt, UTC).strftime('%H:%M')} UTC")
                time.sleep(RETRY_EVERY)
        GARMIN.update(status="error", detail=None,
                      error=f"Still rate-limited after {MAX_ATTEMPTS} spaced attempts "
                            "(~7h) — Garmin may be blocking this IP for longer; tell Claude.")
        telegram("🏃 PaceForge: Garmin sign-in still rate-limited after ~7h of retries.")
    threading.Thread(target=work, daemon=True).start()


def garmin_mfa(code: str) -> None:
    GARMIN.update(status="authenticating", error=None, at=now())

    def work() -> None:
        try:
            if _GARMIN_CLIENT is None:
                raise RuntimeError("no login in progress — start again")
            with _GarminProxy():
                _GARMIN_CLIENT.complete_mfa(code)
            _garmin_finish()
        except Exception as e:
            GARMIN.update(status="error", error=f"{type(e).__name__}: {e}", at=now())
    threading.Thread(target=work, daemon=True).start()


# ── ported inline-Python transforms (save-*.yml) — pure, tested ──

def upsert_rpe(entry: dict, data_dir: Path) -> None:
    rpe = int(entry["rpe"])
    assert 1 <= rpe <= 10, "rpe must be 1-10"
    aid = entry.get("activity_id")
    clean = {
        "activity_id": int(aid) if aid is not None else None,
        "date": str(entry["date"])[:10],
        "rpe": rpe,
        "duration_min": float(entry["duration_min"]) if entry.get("duration_min") else None,
        "notes": (str(entry.get("notes") or "")[:500] or None),
        "source": "web",
    }
    path = data_dir / "rpe.json"
    try:
        entries = json.loads(path.read_text()).get("entries") or []
    except FileNotFoundError:
        entries = []
    if clean["activity_id"] is not None:
        entries = [e for e in entries if e.get("activity_id") != clean["activity_id"]]
    else:
        entries = [e for e in entries
                   if e.get("activity_id") is not None or e.get("date") != clean["date"]]
    entries.append(clean)
    entries.sort(key=lambda e: str(e.get("date") or ""))
    path.write_text(json.dumps({"entries": entries}, indent=2))


def append_ride(entry: dict, data_dir: Path) -> None:
    def num(key, lo, hi, required=False):
        v = entry.get(key)
        if v is None:
            assert not required, f"{key} required"
            return None
        v = float(v)
        assert lo <= v <= hi, f"{key} out of range"
        return round(v, 1)

    clean = {
        "date": str(entry["date"])[:19],
        "workout": (str(entry.get("workout") or "Free ride")[:120]),
        "duration_sec": int(num("duration_sec", 1, 86400, required=True)),
        "avg_power": num("avg_power", 0, 2000),
        "np": num("np", 0, 2000),
        "if": num("if", 0, 3),
        "tss": num("tss", 0, 1000),
        "kj": num("kj", 0, 10000),
        "avg_hr": num("avg_hr", 0, 250),
        "avg_cadence": num("avg_cadence", 0, 200),
        "ftp": num("ftp", 50, 600),
        "notes": (str(entry.get("notes") or "")[:500] or None),
        "source": "web",
    }
    path = data_dir / "bike" / "rides.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rides = json.loads(path.read_text()).get("rides") or []
    except FileNotFoundError:
        rides = []
    rides = [r for r in rides if r.get("date") != clean["date"]]  # retry-idempotent
    rides.append(clean)
    rides.sort(key=lambda r: str(r.get("date") or ""))
    path.write_text(json.dumps({"rides": rides}, indent=2))


def patch_bike_profile(patch: dict, data_dir: Path, today: str | None = None) -> None:
    path = data_dir / "bike" / "profile.json"
    try:
        profile = json.loads(path.read_text())
    except FileNotFoundError:
        profile = {"ftp": None, "ftp_history": [], "weight_kg": None, "wprime_j": 20000}
    if patch.get("ftp") is not None:
        ftp = int(patch["ftp"])
        assert 50 <= ftp <= 600, "ftp out of range"
        if ftp != profile.get("ftp"):
            profile["ftp"] = ftp
            profile.setdefault("ftp_history", []).append({
                "date": today or datetime.now(UTC).date().isoformat(),
                "ftp": ftp,
                "source": str(patch.get("source") or "manual")[:40],
            })
    if patch.get("weight_kg") is not None:
        w = float(patch["weight_kg"])
        assert 30 <= w <= 200, "weight out of range"
        profile["weight_kg"] = w
    if patch.get("wprime_j") is not None:
        wp = int(patch["wprime_j"])
        assert 5000 <= wp <= 50000, "wprime out of range"
        profile["wprime_j"] = wp
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2))


def pending_analyses(data_dir: Path) -> list[str]:
    plan = json.loads((data_dir / "plan.json").read_text())
    ids = []
    for wk in plan.get("weeks", []):
        for wo in wk.get("workouts", []):
            if wo.get("completed") and wo.get("matched_activity_ids"):
                aid = wo["matched_activity_ids"][0]
                if not (data_dir / "analyses" / f"{aid}.md").exists():
                    ids.append(str(aid))
    return ids


# ── jobs (1:1 with .github/workflows) ──

def job_sync(run: Run, inputs: dict) -> None:
    run.step("Sync from Garmin")
    rc = sh(run, pf("sync"), check=False)
    run.step("Commit data if changed")   # always — sync-status.json honesty
    commit_push(run, ["data/"], "data: daily Garmin sync")
    publish(run)
    run.step("Morning brief → Telegram")
    p = subprocess.run(pf("brief"), cwd=REPO_DIR, capture_output=True, text=True, timeout=300)
    if p.returncode == 0:
        telegram(p.stdout, pre=True, title="🏃 PaceForge morning brief")
    if rc != 0:
        # replaces the sync-failure GitHub issue
        telegram("PaceForge Garmin sync FAILED — check data/sync-status.json. "
                 "If the token expired (~yearly), run `paceforge login` on the VM.")
        raise RuntimeError("paceforge sync failed")
    dispatch("analyze", {})   # workflow_run: analyze after sync


def job_analyze(run: Run, inputs: dict) -> None:
    run.step("Find unanalysed completed workouts")
    ids = pending_analyses(REPO_DIR / "data")
    run.log(f"pending: {ids or 'none'}")
    if not ids:
        return
    run.step("Write analyses with the coach")
    claude_step(run, (
        'Use the coach skill in .claude/skills/coach/ — the "Per-activity analysis" '
        f"section. Write data/analyses/{{id}}.md for each of these Garmin activity ids "
        f"that doesn't have one yet: {','.join(ids)}. "
        "Use data/activities.json, data/details/{id}.json, the matched plan workout "
        "in data/plan.json, and data/profile.json. Be specific (real pace/HR/distance "
        "numbers). Then commit the new data/analyses/*.md files and push to master."
    ), tools="Bash(git:*),Read,Write,Glob,Grep,TodoWrite")
    publish(run)


def job_plan(run: Run, inputs: dict) -> None:
    mode = inputs.get("mode") or "create"
    event, level = inputs.get("event_type") or "HYROX", inputs.get("level") or "intermediate"
    target = inputs.get("target_date") or ""
    run.step("Build / reassess plan (running-only)")
    if mode == "reassess":
        sh(run, pf("adapt"), check=False)
    else:
        days = (inputs.get("days") or "tuesday,thursday,saturday,sunday").replace(" ", "")
        cmd = pf("plan", "--goal", event, "--date", target, "--level", level, "--days", days)
        if inputs.get("long_run_day"):
            cmd += ["--long-run-day", str(inputs["long_run_day"])]
        if inputs.get("goal_time"):
            cmd += ["--target-time", str(inputs["goal_time"])]
        sh(run, cmd)
        plan_path = REPO_DIR / "data" / "plan.json"
        p = json.loads(plan_path.read_text())
        p["accepted"] = True
        plan_path.write_text(json.dumps(p, indent=2, default=str))
    sh(run, pf("validate"), check=False)
    sh(run, pf("plan-md"))
    run.step("Commit scaffold (safety net — always a plan)")
    commit_push(run, ["data/plan.json", "plan.md"], f"plan: {event} for {target} ({level})")
    publish(run)
    if mode == "create":
        run.step("Enrich with AI coach")
        try:
            claude_step(run, (
                f"data/plan.json already holds a valid, committed, running-only {event} plan "
                "(scaffolded + accepted). The engine now owns session variety, progression, and "
                "structure — do NOT rewrite sessions, reshuffle variants, rebuild the plan, or "
                "change the event, target date, training days, or paces. Your job is the "
                "athlete-specific judgement layer:\n"
                "- Write a specific coaching note on every workout: what today's session does "
                "for THIS athlete (readiness, RPE history, cadence flag, HYROX load on off-days) "
                "— never restate what the session obviously is.\n"
                '- Adapt to signals in data/profile.json (low training_readiness or hrv_status '
                '"Low" → swap a quality day for easy that week).\n'
                "- Fill the plan-level rationale and tips from data/profile.json evidence.\n"
                "Keep every workout a running type (never hyrox_mixed / cross_training) and keep "
                '"accepted": true. Then run `paceforge validate` (must pass), and commit '
                "data/plan.json (and plan.md if you regenerate it) and push to master. If you "
                "run low on turns, commit what you have rather than stopping."
            ), tools="Bash(paceforge:*),Bash(python:*),Bash(python3:*),Bash(git:*),"
                     "Read,Write,Edit,MultiEdit,Glob,Grep")
        except Exception as e:       # continue-on-error: scaffold is already committed
            run.log(f"enrichment failed (non-fatal): {e}")
        publish(run)
    run.step("Complete job")


def job_coach(run: Run, inputs: dict) -> None:
    task = inputs.get("instruction") or "Review last week and write week-review.md."
    weekly = inputs.get("_weekly", False)
    run.step("Sync from Garmin")
    sh(run, pf("sync"), check=False)   # non-fatal — coach can work from existing data
    run.step("Run coach")
    claude_step(run, (
        "Use the coach skill in .claude/skills/coach/.\n"
        "The athlete's request is in the COACH_TASK environment variable — read it and do it.\n"
        "Then run `paceforge validate`, regenerate plan.md if the plan changed, and "
        "commit any changes to data/, plan.md, and week-review.md and push to master."
    ), tools="Bash(paceforge:*),Bash(python:*),Bash(python3:*),Bash(git:*),"
             "Read,Write,Edit,MultiEdit,Glob,Grep,TodoWrite",
       env={"COACH_TASK": task})
    publish(run)
    if weekly:
        run.step("Notify weekly review")
        wr = REPO_DIR / "week-review.md"
        if wr.exists():
            telegram(wr.read_text()[:600], pre=True, title="📊 PaceForge weekly review")


def job_push(run: Run, inputs: dict) -> None:
    run.step("Push plan week to Garmin")
    cmd = pf("push")
    if inputs.get("week"):
        cmd += ["--week", str(inputs["week"])]
    if str(inputs.get("dry_run")).lower() == "true":
        cmd += ["--dry-run"]
    sh(run, cmd)
    run.step("Commit updated plan")
    commit_push(run, ["data/plan.json"], "data: record Garmin workout ids from push")
    publish(run)


def job_autosync(run: Run, inputs: dict) -> None:
    run.step("Autosync plan weeks to Garmin")
    sh(run, pf("autosync"))
    run.step("Commit updated plan")
    commit_push(run, ["data/plan.json"], "data: weekly Garmin autosync")
    publish(run)


def job_recalibrate(run: Run, inputs: dict) -> None:
    run.step("Recalibrate paces")
    cmd = pf("recalibrate", "--delta", str(inputs["delta"]))
    if str(inputs.get("force")).lower() == "true":
        cmd += ["--force"]
    sh(run, cmd)
    sh(run, pf("plan-md"))
    run.step("Commit updated plan")
    commit_push(run, ["data/plan.json", "plan.md"], f"plan: pace recalibration {inputs['delta']} VDOT")
    publish(run)


def job_calendar_edit(run: Run, inputs: dict) -> None:
    sid, action = str(inputs["session_id"]), str(inputs["action"])
    run.step("Edit calendar + sync Garmin")
    cmd = pf("calendar-edit", sid, action)
    if inputs.get("new_date"):
        cmd += ["--new-date", str(inputs["new_date"])]
    sh(run, cmd)
    run.step("Commit updated plan")
    commit_push(run, ["data/plan.json"], f"calendar: {action} session {sid}")
    publish(run)


def job_garmin_delete(run: Run, inputs: dict) -> None:
    run.step("Delete pushed workouts from Garmin")
    sh(run, pf("garmin-delete"))
    run.step("Commit updated plan")
    commit_push(run, ["data/plan.json"], "chore: clear Garmin workout ids after delete")
    publish(run)


def job_garmin_clear_calendar(run: Run, inputs: dict) -> None:
    dry = str(inputs.get("dry_run", "true")).lower() != "false"
    run.step("Clear Garmin calendar")
    cmd = pf("garmin-clear-calendar", "--days", str(inputs.get("days") or "60"))
    if dry:
        cmd += ["--dry-run"]
    sh(run, cmd)
    if not dry:
        run.step("Commit cleared workout ids")
        commit_push(run, ["data/plan.json"],
                    "chore: clear future Garmin workout ids after calendar wipe")
        publish(run)


def job_hyrox(run: Run, inputs: dict) -> None:
    mode = inputs.get("mode") or "profile"
    gender = inputs.get("gender") or "M"
    run.step(f"HYROX {mode}")
    if mode == "profile":
        sh(run, pf("hyrox-import-profile", str(inputs["slug"]), "--gender", gender))
    elif mode == "import":
        cmd = pf("hyrox-import", str(inputs["name"]), "--gender", gender)
        if inputs.get("firstname"):
            cmd += ["--firstname", str(inputs["firstname"])]
        if inputs.get("urls"):
            cmd += ["--urls", str(inputs["urls"])]
        sh(run, cmd)
    else:
        cmd = pf("hyrox-search", str(inputs["name"]), "--gender", gender)
        if inputs.get("firstname"):
            cmd += ["--firstname", str(inputs["firstname"])]
        sh(run, cmd)
    run.step("Commit HYROX data")
    commit_push(run, ["data/hyrox.json", "data/hyrox_preview.json"], f"data: HYROX {mode}")
    publish(run)


def _save_job(transform, commit_path: str, msg: str):
    def job(run: Run, inputs: dict) -> None:
        run.step(f"Update {commit_path} (validated)")
        data = inputs.get("data")
        entry = json.loads(data) if isinstance(data, str) else data
        transform(entry, REPO_DIR / "data")
        run.step("Commit")
        commit_push(run, [commit_path], msg)
        publish(run)
    return job


JOBS = {
    "sync": job_sync,
    "analyze": job_analyze,
    "plan": job_plan,
    "coach": job_coach,
    "push": job_push,
    "autosync": job_autosync,
    "recalibrate": job_recalibrate,
    "calendar-edit": job_calendar_edit,
    "garmin-delete": job_garmin_delete,
    "garmin-clear-calendar": job_garmin_clear_calendar,
    "hyrox": job_hyrox,
    "save-rpe": _save_job(upsert_rpe, "data/rpe.json", "data: log session RPE"),
    "save-ride": _save_job(append_ride, "data/bike/rides.json", "data: log bike ride"),
    "save-bike-profile": _save_job(patch_bike_profile,
                                   "data/bike/profile.json", "data: update bike profile"),
    "save-events": _save_job(lambda e, d: (d / "events.json").write_text(json.dumps(e, indent=2)),
                             "data/events.json", "data: update upcoming events"),
    "save-benchmarks": _save_job(lambda e, d: (d / "benchmarks.json").write_text(json.dumps(e, indent=2)),
                                 "data/benchmarks.json", "data: update strength benchmarks"),
}


def dispatch(job: str, inputs: dict) -> int:
    fn = JOBS[job]
    run = Run(job)

    def worker() -> None:
        with JOB_LOCK:
            run.rec.update(status="in_progress", run_started_at=now())
            try:
                fn(run, inputs)
                run.finish(True)
            except Exception as e:
                run.log(f"FAILED: {e}")
                run.finish(False)
                if job not in ("sync",):   # sync alerts itself with a specific message
                    telegram(f"PaceForge job '{job}' failed (run {run.id}): {e}")
    threading.Thread(target=worker, daemon=True).start()
    return run.id


# ── web auth: cookie session with a real login page (Victor: no basic-auth
# prompts). Caddy just proxies /paceforge/* here; requests that came through
# Caddy carry X-Forwarded-For and need a session — direct localhost calls
# (systemd timers, debugging) stay open exactly as before. ──

COOKIE = "pf_session"
COOKIE_PATH = os.environ.get("PF_COOKIE_PATH", "/paceforge")
SESSION_TTL = 180 * 86400
SESSIONS_FILE = STATE_DIR / "sessions.json"
_SESSIONS: dict[str, float] = {}


def _load_sessions() -> None:
    if SESSIONS_FILE.exists():
        _SESSIONS.update(json.loads(SESSIONS_FILE.read_text()))


def _new_session() -> str:
    tok = secrets.token_urlsafe(32)
    _SESSIONS[tok] = time.time()
    for t, ts in list(_SESSIONS.items()):   # prune expired
        if time.time() - ts > SESSION_TTL:
            del _SESSIONS[t]
    SESSIONS_FILE.write_text(json.dumps(_SESSIONS))
    return tok


_LOGIN_BRAKE = threading.Lock()   # serialize failed-login sleeps across threads


def check_login(user: str, password: str) -> bool:
    """scrypt hash + constant-time compares; PF_WEB_PASS_SCRYPT = '<salt_hex>$<hash_hex>'.
    Browsers autofill the email in the username box — accept both spellings."""
    conf = os.environ.get("PF_WEB_PASS_SCRYPT", "")
    want_user = os.environ.get("PF_WEB_USER", "").lower()
    email = os.environ.get("PACEFORGE_GARMIN_EMAIL", "").lower()
    if "$" not in conf or not want_user:
        return False
    salt, want = conf.split("$", 1)
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    u = user.strip().lower()
    user_ok = hmac.compare_digest(u, want_user) | (bool(email) & hmac.compare_digest(u, email))
    return bool(user_ok & hmac.compare_digest(got, want))


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PaceForge — sign in</title><style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0f14;color:#e6edf3;font:16px/1.5 system-ui,-apple-system,sans-serif}
form{background:#11161d;border:1px solid #232b36;border-radius:12px;padding:32px;width:300px}
h1{font-size:1.2rem;margin:0 0 18px}label{display:block;font-size:.8rem;color:#8b949e;margin:12px 0 4px}
input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #2d3743;
background:#0b0f14;color:#e6edf3;font-size:1rem}
button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:8px;background:#2f81f7;
color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
#err{color:#f85149;font-size:.85rem;min-height:1.2em;margin-top:10px}</style></head><body>
<form id="f"><h1>🏃 PaceForge</h1>
<label for="u">User</label><input id="u" autocomplete="username" autocapitalize="none">
<label for="p">Password</label><input id="p" type="password" autocomplete="current-password">
<button>Sign in</button><div id="err"></div></form>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await fetch('%COOKIE_PATH%/api/auth/login', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user: document.getElementById('u').value.trim(),
                          password: document.getElementById('p').value}),
  });
  if (r.ok) location.reload();
  else document.getElementById('err').textContent = 'Wrong user or password.';
});
</script></body></html>""".replace("%COOKIE_PATH%", COOKIE_PATH)


# ── HTTP ──

def run_json(rec: dict) -> dict:
    return {**rec, "html_url": f"api/gh/runs/{rec['id']}/log",
            "run_started_at": rec.get("run_started_at") or rec["created_at"]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body=None, ctype="application/json"):
        raw = b"" if body is None else (body if isinstance(body, bytes)
                                        else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):  # quiet
        pass

    def _route(self) -> str:
        """Caddy strips only /paceforge, the frontend prefixes api/ — drop it here."""
        path = urllib.parse.urlparse(self.path).path
        return path[4:] if path.startswith("/api/") else path

    def _authed(self) -> bool:
        if "X-Forwarded-For" not in self.headers:
            return True   # direct localhost (timers, curl) — same trust as before
        cookies = dict(p.strip().split("=", 1) for p in
                       (self.headers.get("Cookie") or "").split(";") if "=" in p)
        tok = cookies.get(COOKIE, "")
        return tok in _SESSIONS and time.time() - _SESSIONS[tok] < SESSION_TTL

    def do_GET(self):
        path = self._route()
        query = urllib.parse.urlparse(self.path).query
        q = urllib.parse.parse_qs(query)
        if path == "/healthz":
            return self._send(200, {"ok": True})
        if not self._authed():
            if path.startswith(("/gh/", "/garmin/", "/runs", "/run/")):
                return self._send(401, {"message": "sign in first"})
            return self._send(200, LOGIN_HTML.encode(), "text/html; charset=utf-8")
        if path == "/" or path == "/index.html":
            return self._static(REPO_DIR / "web" / "index.html")
        if path.startswith("/data/"):
            return self._static(REPO_DIR / path.lstrip("/"), root="data")
        if path == "/garmin/status":
            return self._send(200, dict(GARMIN))
        if path == "/runs":
            return self._send(200, [run_json(r) for r in RUNS[-30:][::-1]])
        m = re.fullmatch(r"/(?:gh/)?runs/(\d+)/log", path)
        if m:
            p = next(iter(STATE_DIR.glob(f"run-{m.group(1)}-*.log")), None)
            return self._send(200, p.read_bytes() if p else b"no log", "text/plain; charset=utf-8")
        m = re.fullmatch(r"/gh/repos/[^/]+/[^/]+/actions/workflows/([^/]+)/runs", path)
        if m:
            job = m.group(1).removesuffix(".yml")
            per = int(q.get("per_page", ["5"])[0])
            runs = [run_json(r) for r in RUNS if r["name"] == job][::-1][:per]
            return self._send(200, {"workflow_runs": runs})
        m = re.fullmatch(r"/gh/repos/[^/]+/[^/]+/actions/runs/(\d+)/jobs", path)
        if m:
            rec = next((r for r in RUNS if r["id"] == int(m.group(1))), None)
            return self._send(200, {"jobs": [{"steps": rec["steps"]}] if rec else []})
        m = re.fullmatch(r"/gh/repos/[^/]+/[^/]+/contents/(.+)", path)
        if m:
            rel = urllib.parse.unquote(m.group(1))
            f = (REPO_DIR / rel).resolve()
            # data/ only — the portal polls analyses; nothing else is served raw
            if not str(f).startswith(str((REPO_DIR / "data").resolve())) or not f.is_file():
                return self._send(404, {"message": "Not Found"})
            return self._send(200, {"content": base64.b64encode(f.read_bytes()).decode(),
                                    "encoding": "base64"})
        if re.fullmatch(r"/gh/repos/[^/]+/[^/]+/issues", path):
            return self._send(200, [])
        if re.fullmatch(r"/gh/repos/[^/]+/[^/]+", path):
            return self._send(200, {"full_name": "local/paceforge"})
        return self._static(REPO_DIR / "web" / path.lstrip("/"))   # bike/ modules, assets

    def _static(self, f: Path, root: str = "web"):
        f = f.resolve()
        if not str(f).startswith(str((REPO_DIR / root).resolve())) or not f.is_file():
            return self._send(404, {"message": "Not Found"})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        return self._send(200, f.read_bytes(), ctype)

    def do_POST(self):
        path = self._route()
        if path == "/auth/login":
            b = self._body()
            if not check_login(str(b.get("user") or ""), str(b.get("password") or "")):
                with _LOGIN_BRAKE:   # global, not per-thread: N parallel guesses ≈ N seconds
                    time.sleep(1)
                return self._send(401, {"message": "wrong user or password"})
            tok = _new_session()
            self.send_response(204)
            self.send_header("Set-Cookie",
                             f"{COOKIE}={tok}; Path={COOKIE_PATH}; Max-Age={SESSION_TTL}; "
                             "HttpOnly; Secure; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if not self._authed():
            return self._send(401, {"message": "sign in first"})
        if path == "/garmin/login":
            b = self._body()
            email = str(b.get("email") or os.environ.get("PACEFORGE_GARMIN_EMAIL") or "")
            if not b.get("password") or not email:
                return self._send(400, {"message": "email and password required"})
            garmin_login_start(email, str(b["password"]))
            return self._send(202, {"status": "authenticating"})
        if path == "/garmin/mfa":
            code = str(self._body().get("code") or "").strip()
            if not code:
                return self._send(400, {"message": "code required"})
            garmin_mfa(code)
            return self._send(202, {"status": "authenticating"})
        m = re.fullmatch(r"/run/([a-z0-9-]+)", path)
        if m and m.group(1) in JOBS:
            return self._send(200, {"id": dispatch(m.group(1), self._body())})
        m = re.fullmatch(r"/gh/repos/[^/]+/[^/]+/actions/workflows/([^/]+)/dispatches", path)
        if m:
            job = m.group(1).removesuffix(".yml")
            if job not in JOBS:
                return self._send(404, {"message": f"unknown job {job}"})
            dispatch(job, self._body().get("inputs") or {})
            return self._send(204)
        if re.fullmatch(r"/gh/repos/[^/]+/[^/]+/issues", path):
            b = self._body()
            task = (b.get("title", "") + "\n\n" + b.get("body", "")).strip()
            rid = dispatch("coach", {"instruction": task})
            return self._send(201, {"number": rid, "html_url": f"api/gh/runs/{rid}/log"})
        return self._send(404, {"message": "Not Found"})


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if "--publish" in sys.argv:
        publish()
        return 0
    _load_sessions()
    global _NEXT_ID
    try:   # resume run-id sequence + history across restarts
        for line in (STATE_DIR / "runs.jsonl").read_text().splitlines()[-50:]:
            RUNS.append(json.loads(line))
        _NEXT_ID = max((r["id"] for r in RUNS), default=0) + 1
    except FileNotFoundError:
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"paceforge-runner on 127.0.0.1:{PORT}, repo {REPO_DIR}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
