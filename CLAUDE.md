# PaceForge

A serverless running coach, one athlete per copy. No backend, no database, no
LLM API key — **Claude is the coach** (see `.claude/skills/coach/`), the
`paceforge` Python package does the deterministic maths and the Garmin I/O, and
`data/*.json` (git-tracked) is the only state. Several athletes share the app by
running several instances of it, not by the app growing accounts — see
§Multi-user below, and never assume this checkout is the only one running.

## VM runner — the backend (ACTIVE since 2026-07-21, the only path since 2026-07-22)

The app runs entirely on the claude-dev VM:
`https://claude-dev-vperrod.westeurope.cloudapp.azure.com/paceforge/`.
GitHub Actions and Pages are **gone** (Victor 2026-07-22: never going back, and
the repo stays private) — `.github/workflows/` is deleted, there is no fallback
backend, and nothing may reintroduce a dependency on either.
Auth is a cookie-session login page served by the runner (user `vperrod`;
scrypt hash in the env file — no Caddy basic auth, Caddy only proxies
`/paceforge/*` to the runner). `scripts/runner.py` (systemd user unit
`paceforge-runner`, 127.0.0.1:8123) serves `web/` + `data/` straight from this
checkout and runs every job. The portal reaches it at `/paceforge/api/*` (`API`
const in `web/index.html`); the `/gh/repos/<o>/<r>/…` URL shapes are inherited
from the Actions era and kept because both sides agree on them — owner and repo
are ignored, and no token is involved (the session cookie is the auth). Timers: `paceforge-sync` 3×/day 06:45/13:00/21:00 Dublin (morning pass
sends the Telegram brief + dispatches the `daily` coach read; every pass dispatches
`analyze`), `paceforge-autosync`
daily 06:20 UTC (Garmin reconcile), `paceforge-coach` Mon 07:19 UTC (units in `ops/`; they call
the runner's loopback-only internal port — 8223 for Victor, `PACEFORGE_RUNNER_INTERNAL_PORT`
(= public port + 100) for instances — which is trusted and bypasses the session check by
design; the public port Caddy fronts always needs a session). Secrets: `~/.config/paceforge/env`
(0600). Victor's own checkout pushes data commits to `origin` (Forgejo, primary
since 2026-08-03) with the `github` mirror as fallback; per-athlete instances
have no remote at all.
Claude steps (plan enrichment, analyses, coach) run the local `claude` CLI.
Garmin (re)login happens in the portal — Settings → "Connect Garmin"
(password → optional MFA; runner endpoints `/garmin/login|mfa|status`) — no
TTY needed; on success the runner kicks a full sync automatically. The
handshake egresses through Cloudflare WARP (`warp-svc`, socks5 proxy mode on
127.0.0.1:40000, `PF_GARMIN_PROXY` in the env file) because Garmin's SSO
rate-limits per IP and the VM's own IP burns fast; if a login 429s anyway,
the runner retries every 45 min and Telegrams on connect/MFA/failure.
Debug: `GET /paceforge/api/runs`, logs in `~/.local/state/paceforge-runner/`.
The runner is permanent: `claude-config os/github-restore-checklist.md` §0c is
now a keep-it note, not a retirement plan.

## Multi-user (sharing the portal with friends)

Each athlete gets **their own instance**, not a tenant inside one app: their own
checkout under `~/projects/paceforge-users/<name>/`, their own `data/` (local git
history, **no remote** — `commit_push` skips the push when there is no `origin`),
their own Garmin token dir, their own runner port (8124+) and their own login,
reached at `/pf/<name>/` (`PF_COOKIE_PATH` scopes the session cookie, so one
portal's cookie is useless on another). Isolation is the OS's, so no job, path or
Garmin client can cross between athletes. Victor's own instance is unchanged:
`/paceforge/`, port 8123, the un-templated units, and the only one with Telegram
(`telegram()` no-ops without `TG_*`, so friends simply get none).

```bash
scripts/users.py add alice        # clone + env + units + Caddy route, prints the password
scripts/users.py list
scripts/users.py update [alice]   # copy code from this checkout into instances, restart
scripts/users.py remove alice --yes
```

The venv is **shared by symlink** — `paceforge` is installed editable, so every
instance runs this checkout's Python package and a fix in `src/` reaches everyone
at once. Only `web/`, `scripts/`, `ops/`, `.claude/` come from the instance's own
copy (`runner.py` resolves its own path to find the instance root, so it cannot be
a symlink) — which is why code changes need `scripts/users.py update`, and why
that update is a file copy, not a `git pull`: this repo commits Victor's own
training data to the same branch, and pulling it would drag his data into theirs.

A friend's onboarding is: open the URL → sign in → Settings → **Connect Garmin**
with their own account. Nothing else is provisioned by hand — the runner persists
the email they logged in with to `data/token-meta.json`, and
`actions._garmin_email()` reads it back when the env has none. Their bike is
browser-side Web Bluetooth as before, against their own `data/bike/profile.json`.
Do the Garmin logins **one athlete at a time**: they share one WARP egress IP and
Garmin rate-limits per IP (the runner rides out a 429 by retrying every 45 min).

Coach steps run the same `claude` CLI on Victor's account for everyone; the sync
timers carry `RandomizedDelaySec` so instances don't pile onto the machine at
06:45 together.

## Sensitive data handling

These files MUST NOT be committed to any repo (Victor's private repo, friends’
no-remote checkouts, forks, CI artifacts, or patch/diff outputs):

- `data/profile.json` — full fitness profile, real name, PII
- `data/history.jsonl` — daily wellness + load + HRV + sleep, identifiable over time
- `data/hyrox.json` — race history, split series, name
- `data/hyrox_preview.json` — candidate scrape list with athlete names
- `data/token-meta.json` — login email, token provenance
- `data/sync-status.json` — sync outcomes paired with user state
- `data/rpe.json` — logged session effort ratings with comments
- `data/fitness.json` — computed fitness metrics over personal timeline
- `data/details/` — per-activity JSON blobs with heart-rate/position traces

### Enforcement

- `.gitignore` blocks these paths; do NOT remove the sensitive-data block.
- `store.py` defaults to `data/` but supports `PACEFORGE_DATA_DIR` for locating
  private storage outside the public checkout when needed.
- Victor’s instance keeps the existing git-tracked `data/` layout for his private
  checkout only. Shared/public contexts should set `PACEFORGE_DATA_DIR` to an
  untracked path before any job writes state.
- `scripts/users.py` already provisions each friend with their own isolated checkout
  and `data/` — no remote, so pushes cannot accidentally expose data.
- Before attaching or publishing diffs, patches, or screenshots, sanitize/redact
  these files. If history already contains sensitive commits, assume exposure and
  rotate tokens / review access rather than depending on a simple history rewrite.

Migration note (2026-07-30): these entries were added after a PII/health-telemetry
audit. Existing checkouts should verify `.gitignore` covers the full sensitive set;
older clones should be cleaned before sharing.

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
  rotation, deload time trials — always clamps `total_weeks` to what's
  actually available between today and race day (`_generate_template_plan`
  defaults `start_date` to today when unset, since nothing ever passes one
  explicitly); the clamp maps the compressed plan's weeks onto the *native*
  template's week numbers via `_template_week()` rather than truncating the
  front of the fixed-length `volume_progression`/`phases` arrays — a close
  race must still reach the template's own Peak/Taper, not get cut off
  before it and land on full volume the week of the race), session-variant
  tables (`variants.py`,
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
  written via the `save-ride` / `save-bike-profile` jobs; each saved ride carries a
  downsampled `trace` ([sec, watts, hr] ≤400 points, sanitized in `append_ride`)
  that powers the clickable ride-detail view (power/HR chart + time-in-zone). Rides are digested
  like Garmin work: `store.load_bike_rides()` feeds `compute_daily_load`
  (power TSS × `_TSS_TO_TRIMP` onto the TRIMP scale, `method="tss"`; strap-HR
  TRIMP fallback) at both `compute_load_recovery` call sites, and the web's
  `allActivities()` merges them into the feed/Calendar/Today lists with ids
  `bike:<date>`. Python side: POWER
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

## Jobs (the runner's `JOBS` map; portal buttons and timers dispatch these)
`sync` runs **3×/day (06:45 / 13:00 / 21:00 Dublin)** so runs are matched and
coach-analysed the same day; the morning pass (and only that one) pushes
`paceforge brief --telegram` (`TG_TOKEN` + `TG_CHAT_ID`; skipped when unset)
and dispatches `daily` — the coach's morning read → `data/daily-brief.json`,
rendered as the lead card on the Today page. Every sync dispatches `analyze`
(per-activity coach analyses). Its worklist is `pending_analyses`: **every** completed
session — all Garmin activity types plus app bike rides (`bike:<date>` ids) — over a
30-day lookback, newest first, 10 per pass; plan matching deliberately does NOT gate
it (unplanned work gets coached too — never reintroduce that filter, thrice-repeated
athlete requirement).
`save-rpe` is the re-evaluation trigger: logging a rating re-matches the plan (so
`user_rpe` lands on the workout) **and deletes that activity's
`data/analyses/<id>.md`** before dispatching `analyze`, because an analysis
written before the rating existed says "no RPE logged" and `pending_analyses`
would skip the id forever. Garmin's own Feel/Effort cannot drive this: neither
`activity-service/activity/{id}` nor the activity-list endpoint returns any
feel/RPE/exertion field (checked 2026-08-04), and the pinned `garminconnect`
fork has no RPE support — the portal buttons are the only source.
`autosync` (daily 06:20 UTC) reconciles the Garmin calendar with the accepted
plan — pushes current + next 2 weeks, deletes stale completed copies and orphaned
scheduled entries (the runner also reconciles after every plan-mutating job);
`recalibrate` applies portal-accepted pace shifts; `plan` scaffolds
deterministically, then Claude enriches notes; `coach`
(Mon 07:19 UTC) writes week-review.md and pushes its headline to Telegram.
`push` and `autosync` **commit plan.json back** (garmin_workout_id persistence —
required for dedup). Job names still carry a `.yml` suffix on the wire (the
portal's dispatch URLs) — the runner strips it; the workflows themselves are gone.
`add-session` (Calendar day view → "+ Add activity") schedules a class as a
**first-class calendar item in `data/calendar.json`** (2026-08-10 decoupling —
`models/calendar.py::ScheduledItem`; the old plan-embedded Workout and the even
older `extra_activities.json` are both gone). The calendar is the athlete's
whole week; the running plan merely contributes its workouts to the same view
and NEVER stores classes. Items are matched to completed Garmin activities by
date + sport family (`actions.match_calendar_items`, runs in every sync's
`_match_plan`; generic "Cardio" items never claim runs), pushed to the Garmin
calendar by `garmin_reconcile` (today → +21d window, id round-trip on the
item), and edited via the same `calendar-edit` job (its id resolves against
plan session_ids OR calendar item_ids). `garmin_reconcile` works with **no
plan at all** — plan passes are skipped, calendar items still push, orphans
still sweep. Optional `repeat_weeks` (1–52) schedules the item weekly.

`match-edit` (activity detail → "Plan match") is the manual override for the
matcher: link pins the activity via `manual_activity_ids` (applied verbatim, so
no later sync can re-assign it), unlink detaches it AND adds it to
`excluded_activity_ids` so the matcher cannot silently put it back. Only Garmin
activities have it — app bike rides (`bike:<date>`) aren't ids `link_activity`
can resolve. The candidate list is unmatched non-rest sessions within ±7 days.

The portal's `saveExtra()` (web/index.html) polls the dispatched job to
actual completion (by run id, not timestamp — the server's `created_at` is
second-truncated and a ms-precision comparison misses real matches) before
calling `planStore.reset()` and re-rendering Calendar on the same day.
Skipping that wait is why a freshly-scheduled class used to not appear
without a manual reload — the job commits async (~1–3s) and the in-memory
+ localStorage plan cache doesn't know to invalidate itself otherwise.

## Auth & secrets (env)
`PACEFORGE_GARMIN_EMAIL`, `GARMIN_TOKEN` (base64 token from `paceforge login`),
`PACEFORGE_GARMIN_TOKEN_DIR` (default `~/.garminconnect`). None are committed.

The VM runner reads its own set from `~/.config/paceforge/env` (Victor) or
`~/.config/paceforge/<name>.env` (an instance, written by `scripts/users.py`):
`PF_WEB_USER` + `PF_WEB_PASS_SCRYPT` (`'<salt_hex>$<hash_hex>'`, scrypt
n=2¹⁴/r=8/p=1 — mint one with `scripts/users.py`'s `scrypt_conf`), `PF_COOKIE_PATH`
(scopes the session cookie to that portal), `PACEFORGE_RUNNER_PORT`,
`PACEFORGE_RUNNER_STATE`, `PACEFORGE_GARMIN_TOKEN_DIR`, `PF_GARMIN_PROXY` (WARP
socks5 for the Garmin handshake), and `TG_TOKEN`/`TG_CHAT_ID` — **Victor's file
only**; `telegram()` no-ops without them, which is exactly how friends get no
notifications. `PACEFORGE_GARMIN_EMAIL` is absent from an instance's file on
purpose: the runner persists the address from the portal login into
`data/token-meta.json` and `actions._garmin_email()` reads it back.
(`.env.example` covers only the CLI variables — editing it is blocked by the
global `.env.*` guard.)

`paceforge login` is interactive (password + MFA) — it can't run in a non-interactive shell
(piped/agent `!` → `EOFError`); use a real terminal, or just use the portal's Connect Garmin.
The OAuth2 token is short-lived but every sync re-dumps the refreshed one, so a running
instance maintains itself; the OAuth1 token behind it expires ~yearly. `GARMIN_TOKEN` +
`paceforge export-token` are the portable backup/restore path for a token dir (moving an
athlete to another machine), not a CI mechanism.

## Style
- Ruff, 100-char lines (see `pyproject.toml`). `from __future__ import annotations` at top.
- Named exports, verb-first functions. Commit messages: `area: short description`.

## Agentic OS

- Registry entry: `paceforge` in `claude-config/os/registry.yaml` (autonomy: `report-only`)
- Cross-project backlog: `claude-config/os/backlog.md` under `## PaceForge`
- Working tasks: `tasks/todo.md` · Lessons after corrections: `tasks/lessons.md`
- At session start, check the registry entry and this project's backlog section.
