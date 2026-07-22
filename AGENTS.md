# PaceForge — Agent Instructions

Serverless running coach, one athlete per copy. No backend, no database, no LLM
API key. **Claude is the coach** (`.claude/skills/coach/`); the `paceforge` package
does the deterministic maths + Garmin I/O; `data/*.json` (git-tracked) is the state.

Other athletes get their own instance (own checkout, `data/`, Garmin token, port,
login) via `scripts/users.py` — see CLAUDE.md §Multi-user before touching paths,
storage keys or `commit_push`. Assume "single-user" means *per process*, never
"there is only one copy running".

Full orientation is in [CLAUDE.md](CLAUDE.md) — read it. Key points:

## Architecture
```
src/paceforge/
├── store.py          # load/save data/* (the "database"): profile, plan, activities,
│                     # details, history, benchmarks, hyrox, rpe, sync-status,
│                     # token-meta
├── actions.py        # all behaviour; CLI + MCP are thin wrappers. sync() (writes
│                     # sync-status.json), analyze(), fitness() (Fitness 2.0),
│                     # plan/push/validate, adapt(), log_rpe()
├── cli.py            # `paceforge` command
├── mcp_server.py     # `paceforge-mcp` stdio server (Claude desktop) — incl. the
│                     # log_rpe + get_fitness tools
├── engine/           # LLM-free maths:
│   ├── vdot, workouts, planner, validate   # plan construction + rules (incl. HYROX
│   │                 # brick/simulation/station-day builders in workouts.py)
│   ├── adaptation.py         # pace recalc + reflow_missed_sessions + readiness_gate
│   ├── analytics.py          # LEGACY snapshot analysis (superseded by Fitness 2.0)
│   ├── durability.py         # running engine: CS/D', EF, decoupling, HRR, 80/20,
│   │                         # effective VO2max…
│   ├── curves.py             # pace-duration curves (fresh / fatigued / seasons)
│   ├── enviro.py             # heat/humidity pace adjustment (uses stored weather)
│   ├── load.py               # CTL/ATL/TSB, ACWR, HRV, sleep, readiness… + sRPE load
│   ├── compliance.py         # plan-vs-actual bands (green/yellow/orange/red) + rollup
│   ├── matching.py           # activity↔workout matching (runs by distance,
│   │                         # hyrox_mixed/cross_training by duration)
│   ├── strength.py           # HYROX stations, hybrid balance (needs benchmarks)
│   └── limiters.py           # ranks limiters → coach_input contract
├── garmin/client.py  # reads metrics + per-sample series (per-endpoint failure
│                     # report), uploads workouts (fitness_equipment sport for HYROX
│                     # with running fallback, delete-by-id dedup)
└── hyrox/            # hyresult.py (per-race ranks+splits via hyresult.com),
                      # analyzer.py + benchmarks.py (cohort gender/division/age tables)
web/index.html        # the GitHub Pages dashboard (reads committed data/*.json)
scripts/build_site_data.py  # precomputes analytics/fitness/hyrox_analysis.json for the web (CI)
data/                 # profile.json, plan.json, activities.json, history.jsonl,
                      # details/{id}.json (splits + time-series), analyses/{id}.md +
                      # analyses/hyrox-{id}.md, hyrox.json, hyrox_analysis.json,
                      # benchmarks.json, events.json, rpe.json (session effort),
                      # sync-status.json (last sync outcome), token-meta.json,
                      # weekly.json, fitness.json, analytics.json
```

## HYROX + events flow (serverless writes)
The browser dispatches a GitHub Action with the user's PAT → the Action runs a CLI command
that writes `data/*.json` + commits → `pages.yml` (which reacts to those workflows in its
`workflow_run` list) rebuilds and redeploys. Mirror this for any new browser-driven write:
- `hyrox.yml` (mode `profile`) → `paceforge hyrox-import-profile <slug>` → `data/hyrox.json`
  from a hyresult.com athlete profile. Dispatched from Settings → HYROX races (paste profile
  URL/slug); the UI polls raw `data/hyrox.json` for the slug. hyresult is the source of truth:
  results.hyrox.com's season-overall ranking drops races and reports season-cumulative ranks,
  whereas hyresult has every race with per-race Overall + Age-group ranks and full splits.
  (The legacy `search`/`import` results.hyrox.com modes still exist in `hyrox.yml`.)
- `save-events.yml` → `data/events.json`.
- `save-benchmarks.yml` → `data/benchmarks.json` (Strength-tab form).
- `save-rpe.yml` → upserts one entry into `data/rpe.json` (the RPE pills on activity
  detail / workout sheet / Today's check-in).
- `build_site_data.py` derives `data/hyrox_analysis.json` (`{races, priorities, progression}`)
  from `hyrox.json` at deploy time.

Sync trust: `sync.yml` refreshes the `GARMIN_TOKEN` secret and commits `data/` even on
failure, and opens/auto-closes a `sync-failure` issue; `data/sync-status.json` is the
UI's freshness signal — never infer freshness from `profile.json` existing.

## The AI / validation split
Deterministic facts (paces, plan structure) stay in code. Claude **proposes** a plan
(scaffold with `paceforge plan`, then personalise), `engine/validate.py` **checks** it.
Never invent paces — the engine derives them.

## Commands
```bash
.venv/bin/ruff check src/ tests/    # lint (must pass before commit)
.venv/bin/pytest tests/ -q          # tests (must pass before push)
.venv/bin/paceforge sync|analyze|plan|validate|adapt|rpe|push|status|hyrox-import-profile
scripts/users.py add|list|update|remove   # per-athlete instances (CLAUDE.md §Multi-user)
```

After changing `web/`, `scripts/` or `.claude/`, run `scripts/users.py update` —
other athletes' instances run their own copy of those directories.

## Conventions
- Python 3.11+, ruff 100-char lines, `from __future__ import annotations` at top.
- One behaviour module (`actions.py`) — keep CLI/MCP as thin wrappers, no duplicated logic.
- Commit messages: `area: short description`. Run ruff + pytest before committing.
