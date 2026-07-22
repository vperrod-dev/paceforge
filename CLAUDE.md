# PaceForge

A single-user, serverless running coach. No backend, no database, no LLM API
key — **Claude is the coach** (see `.claude/skills/coach/`), the `paceforge`
Python package does the deterministic maths and the Garmin I/O, and
`data/*.json` (git-tracked) is the only state.

## VM runner (ACTIVE since 2026-07-21 — GitHub account flagged, ticket 4583559)

While GitHub Actions/Pages are dead, the app runs entirely on the claude-dev VM:
`https://claude-dev-vperrod.westeurope.cloudapp.azure.com/paceforge/`.
Auth is a cookie-session login page served by the runner (user `vperrod`;
scrypt hash in the env file — no Caddy basic auth, Caddy only proxies
`/paceforge/*` to the runner). `scripts/runner.py` (systemd user unit
`paceforge-runner`, 127.0.0.1:8123) serves `web/` + `data/` straight from this
repo AND replaces every workflow 1:1 — the portal talks to it through the same
GitHub-API shapes at `/paceforge/api/gh/*` (`GH_API` const in `web/index.html`;
on github.io it still targets the real GitHub API, so Pages remains the
rollback). Timers: `paceforge-sync` 3×/day 06:45/13:00/21:00 Dublin (morning pass
sends the Telegram brief + dispatches the `daily` coach read; every pass dispatches
`analyze`), `paceforge-autosync`
daily 06:20 UTC (Garmin reconcile), `paceforge-coach` Mon 07:19 UTC (units in `ops/`; they call
127.0.0.1:8123 directly, which bypasses the session check by design — only
Caddy-forwarded requests need a session). Secrets: `~/.config/paceforge/env`
(0600). Data commits push to `origin` as before.
Claude steps (plan enrichment, analyses, coach) run the local `claude` CLI.
Garmin (re)login happens in the portal — Settings → "Connect Garmin"
(password → optional MFA; runner endpoints `/garmin/login|mfa|status`) — no
TTY needed; on success the runner kicks a full sync automatically. The
handshake egresses through Cloudflare WARP (`warp-svc`, socks5 proxy mode on
127.0.0.1:40000, `PF_GARMIN_PROXY` in the env file) because Garmin's SSO
rate-limits per IP and the VM's own IP burns fast; if a login 429s anyway,
the runner retries every 45 min and Telegrams on connect/MFA/failure.
Debug: `GET /paceforge/api/runs`, logs in `~/.local/state/paceforge-runner/`.
Retirement steps when the flag lifts: `claude-config os/github-restore-checklist.md`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # one-time setup
.venv/bin/ruff check src/ tests/        # lint (must pass before commit)
.venv/bin/pytest tests/ -q              # tests (must pass before push)

.venv/bin/paceforge login               # one-time Garmin auth (MFA) → GARMIN_TOKEN
.venv/bin/paceforge sync                # Garmin metrics+activities → data/*.json
.venv/bin/paceforge analyze             # full analytics over the stored profile
.venv/bin/paceforge plan --goal MARATHON --date 2026-10-04 --level intermediate
.venv/bin/paceforge plan-md             # regenerate plan.md deterministically (never hand-write it)
.venv/bin/paceforge validate            # check data/plan.json against the rules
.venv/bin/paceforge adapt [--dry-run]   # reflow missed sessions + readiness-gate hard work
.venv/bin/paceforge recalibrate --delta 0.5 [--force]  # accepted pace shift, future weeks only
.venv/bin/paceforge rpe 7 <activity_id> # log session RPE (HR-less strength/HYROX load)
.venv/bin/paceforge link <activity_id> --date 2026-06-01   # pin activity to a workout (or --session-id)
.venv/bin/paceforge unlink <activity_id>                   # detach + never auto-rematch there
.venv/bin/paceforge brief [--telegram] [--date YYYY-MM-DD]  # morning brief (plain text, or Telegram-HTML)

.venv/bin/paceforge push [--week N] [--dry-run]   # upload a plan week to Garmin
.venv/bin/paceforge autosync            # daily cron: reconcile Garmin with the plan (push 3 weeks, delete stale + orphans)
.venv/bin/paceforge-mcp                 # stdio MCP server (Claude desktop app)
```

## Architecture

- **`data/*.json`** — the database. `profile.json` (UserFitnessProfile),
  `plan.json` (TrainingPlan), `activities.json` (list), `rpe.json` (session
  effort ratings), `sync-status.json` (last sync outcome — the UI's freshness
  signal), `token-meta.json` (login date → token-age warnings). Git is the
  history. Override the dir with `PACEFORGE_DATA_DIR`.
- **`store.py`** — load/save the JSON files via Pydantic. No DB.
- **`actions.py`** — all behaviour (sync, scaffold, analyze, validate, push,
  status, Garmin auth). The CLI and MCP server are thin wrappers over it.
- **`cli.py`** / **`mcp_server.py`** — two entrypoints, same logic.
- **`engine/`** — VDOT maths + percentage pace *bands* (`vdot.py`), workout
  factory (`workouts.py` — easy/long/tempo/cruise/VO2/speed/hills/fartlek plus
  ladders, progressive tempo, alternations, steady-M, blocks long run, time
  trial), plan generator (`planner.py`, LLM-free: volume anchored to actual
  mileage, skeleton-density + goal-feasibility rules, rule-driven long-run
  rotation, deload time trials), session-variant tables (`variants.py`,
  Canova-lever ordered, volume-gated), coaching briefings (`briefings.py` —
  purpose/structure/feel/if_wrong/cue/venue/fuel/warmup per session + week
  intros), `adaptation.py` (reflow + readiness gate), `validate.py` (pace
  ordering, goal feasibility, back-to-back, ramps, frequency-scaled long-run
  cap, consecutive-week session variety), and the Fitness 2.0 modules:
  `durability.py`, `curves.py`, `enviro.py`, `load.py` (incl. sRPE),
  `compliance.py` (plan-vs-actual bands + **pace insights**: heat-adjusted
  actual-vs-window verdicts + rolling pace status), `matching.py`,
  `strength.py`, `limiters.py`. `analytics.py` is the LEGACY snapshot analysis.
- **`garmin/client.py`** — reads metrics, uploads structured workouts (pace.zone
  windows from plan bands, per-step notes ≤200 chars, HR bpm targets, REST
  steps; description ≤500 chars leads with the briefing purpose).
- **`hyrox/`** — race-result analyzer vs field benchmarks.
- **`web/bike/` + `engine/bike.py`** — indoor cycling (Zwift replacement; plan:
  `tasks/bike-section-plan-2026-07-13.md`). Browser-side ES modules (Chrome/Edge
  Web Bluetooth, ES modules → needs http(s), not file://): `trainer.js` (FTMS
  0x1826 ERG/sim control of the KICKR CORE 2, plus a duck-typed `MockTrainer`
  for hardware-free dev), `hr.js`, `zwift-ride.js` (reverse-engineered Ride
  button pods — "RideOn" handshake, protobuf `0x23` bitmap; unverified on real
  hardware until first ride), `workouts.js` (ZWO/ERG/MRC parse + ramp test),
  `metrics.js` (NP/IF/TSS/W'bal, Coggan zones), `recorder.js` + `fit.js`
  (crash-safe recording → valid .FIT, fitdecode-verified), `upload.js`
  (intervals.icu + Strava). Node selftests: `node web/bike/selftest-*.mjs`.
  State: `data/bike/` (profile with FTP history, workout library, rides.json)
  written via `save-ride.yml` / `save-bike-profile.yml`. Python side: POWER
  intensity targets (watts), `sport="bike"` workouts, Garmin `power.zone` push.

## The AI / validation split
Deterministic facts stay in code; judgement is Claude's. The **engine owns**
plan structure, session variety/progression, and the per-session briefings —
Claude (running-plan/coach skills) adds the **athlete-specific layer**: workout
`notes` that read readiness/RPE/history, plan `rationale`/`tips`, adaptations.
Never rewrite engine variety or restate a briefing; never ask the model to
compute paces a formula does exactly. Scaffold with `paceforge plan`,
personalise notes, re-validate, regenerate the human view with
`paceforge plan-md`. Pace changes go through `paceforge recalibrate`
(athlete-accepted, guarded), never hand-edits.

## Scheduled workflows (beyond sync)
`sync.yml` runs **3×/day (06:45 / 13:00 / 21:00 Dublin)** so runs are matched and
coach-analysed the same day; the morning pass (and only that one) pushes
`paceforge brief --telegram` (`TG_TOKEN` + `TG_CHAT_ID` secrets; skipped when unset)
and dispatches `daily.yml` — the coach's morning read → `data/daily-brief.json`,
rendered as the lead card on the Today page. Every sync dispatches `analyze.yml`
(per-activity coach analyses).
`autosync.yml` (daily 06:20 UTC) reconciles the Garmin calendar with the accepted
plan — pushes current + next 2 weeks, deletes stale completed copies and orphaned
scheduled entries (the runner also reconciles after every plan-mutating job); `recalibrate.yml` applies portal-accepted pace shifts;
`plan.yml` scaffolds deterministically, then Claude enriches notes; `coach.yml`
(Mon 07:19 UTC) writes week-review.md and pushes its headline to Telegram
(same `TG_TOKEN` + `TG_CHAT_ID` secrets). push.yml and autosync.yml **commit plan.json
back** (garmin_workout_id persistence — required for dedup).

## Auth & secrets (env)
`PACEFORGE_GARMIN_EMAIL`, `GARMIN_TOKEN` (base64 token from `paceforge login`),
`PACEFORGE_GARMIN_TOKEN_DIR` (default `~/.garminconnect`). None are committed.

`paceforge login` is interactive (password + MFA) — it can't run in a non-interactive shell
(piped/CI/agent `!` → `EOFError`); use a real terminal. The OAuth2 token is short-lived, so
`sync.yml` refreshes it and writes it back to the `GARMIN_TOKEN` secret each run when the
`ACTIONS_PAT` secret (fine-grained PAT, Secrets R/W) is set; without it, re-set the token by
hand. After a successful login the token is on disk — recover it without re-logging-in via
`paceforge export-token`.

## Style
- Ruff, 100-char lines (see `pyproject.toml`). `from __future__ import annotations` at top.
- Named exports, verb-first functions. Commit messages: `area: short description`.

## Agentic OS

- Registry entry: `paceforge` in `claude-config/os/registry.yaml` (autonomy: `report-only`)
- Cross-project backlog: `claude-config/os/backlog.md` under `## PaceForge`
- Working tasks: `tasks/todo.md` · Lessons after corrections: `tasks/lessons.md`
- At session start, check the registry entry and this project's backlog section.
