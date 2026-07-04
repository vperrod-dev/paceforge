# PaceForge

A single-user, serverless running coach. No backend, no database, no LLM API
key — **Claude is the coach** (see `.claude/skills/coach/`), the `paceforge`
Python package does the deterministic maths and the Garmin I/O, and
`data/*.json` (git-tracked) is the only state.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # one-time setup
.venv/bin/ruff check src/ tests/        # lint (must pass before commit)
.venv/bin/pytest tests/ -q              # tests (must pass before push)

.venv/bin/paceforge login               # one-time Garmin auth (MFA) → GARMIN_TOKEN
.venv/bin/paceforge sync                # Garmin metrics+activities → data/*.json
.venv/bin/paceforge analyze             # full analytics over the stored profile
.venv/bin/paceforge plan --goal MARATHON --date 2026-10-04 --level intermediate
.venv/bin/paceforge validate            # check data/plan.json against the rules
.venv/bin/paceforge adapt [--dry-run]   # reflow missed sessions + readiness-gate hard work
.venv/bin/paceforge rpe 7 <activity_id> # log session RPE (HR-less strength/HYROX load)
.venv/bin/paceforge push [--week N] [--dry-run]   # upload a plan week to Garmin
.venv/bin/paceforge-mcp                 # stdio MCP server (Claude desktop app)
```

## Architecture

- **`data/*.json`** — the database. `profile.json` (UserFitnessProfile),
  `plan.json` (TrainingPlan), `activities.json` (list), `rpe.json` (session
  effort ratings), `sync-status.json` (last sync outcome — the UI's freshness
  signal). Git is the history. Override the dir with `PACEFORGE_DATA_DIR`.
- **`store.py`** — load/save the JSON files via Pydantic. No DB.
- **`actions.py`** — all behaviour (sync, scaffold, analyze, validate, push,
  status, Garmin auth). The CLI and MCP server are thin wrappers over it.
- **`cli.py`** / **`mcp_server.py`** — two entrypoints, same logic.
- **`engine/`** — VDOT maths (`vdot.py`), workout factory (`workouts.py`),
  template planner (`planner.py`, LLM-free), `adaptation.py`, `analytics.py`
  (the health/running analysis), and `validate.py` (plan rule checks).
- **`garmin/client.py`** — reads metrics, uploads structured workouts.
- **`hyrox/`** — race-result analyzer vs field benchmarks.

## The AI / validation split
Deterministic facts stay in code; judgement is Claude's. Claude **proposes** a
plan (guided by the coach skill), `engine/validate.py` **checks** it. Never ask
the model to compute paces a formula does exactly — scaffold with
`paceforge plan`, then personalise and re-validate.

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
