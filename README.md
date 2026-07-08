# PaceForge

A personal, serverless running coach for Garmin. Pulls your Garmin Connect fitness
data, builds and adapts training plans, pushes structured workouts to your watch,
and reviews your training — with **no backend, no database, and no LLM API bill**.

It runs four ways, all free beyond a Claude subscription:
- a **web dashboard** on GitHub Pages — **[vperrod.github.io/paceforge](https://vperrod.github.io/paceforge/)** (single-user, static, reads the committed `data/*.json`),
- **Claude Code** in this repo (run the CLI directly),
- the **Claude desktop app** via a local MCP server,
- **GitHub Actions** — a daily Garmin sync, an auto-analysis of completed workouts, and a weekly auto-review.

## How it works

- **Deterministic maths in code**: VDOT→pace *bands*, workout construction, and a
  coach-grade plan generator live in the `paceforge` package. The engine owns
  structure and variety: volume anchored to your actual mileage (ACWR-safe ramps),
  session variants that progress week over week (Canova levers, volume-gated),
  rule-driven long-run rotation (unstructured alternates with progression / blocks /
  race-pace; dress rehearsal ~3 weeks out), milestone time trials on deload weeks,
  and a full **coaching briefing** on every session (purpose, structure with pace
  windows, feel, failure-mode advice, form cues, fueling).
- **Judgement is Claude's**: athlete-specific notes on top of the briefings
  (readiness trend, RPE history, schedule realism), adaptation, activity analysis,
  and weekly reviews — guided by the coach and running-plan skills.
- **State is files**: everything lives in git-tracked `data/*.json`. Git is the history.

The engine **validates** every plan (paces ordered, goal feasibility vs VDOT, no
back-to-back intense days, sane ramps, frequency-scaled long-run caps, no identical
quality sessions in consecutive weeks) before anything reaches your watch. After
quality sessions, **pace insights** judge your splits against the target windows
(heat-adjusted, HR-guarded) and propose an accept/reject pace recalibration —
future weeks only, rate-limited, frozen near race day.

## Web dashboard

A desktop-first static dashboard ([vperrod.github.io/paceforge](https://vperrod.github.io/paceforge/)),
deployed by `pages.yml` and re-deployed automatically after each sync:

- **Today** (the home tab) — your readiness score with a plain-language go/no-go and
  its dominant driver, today's (or next) planned session, trend arrows (Fitness/CTL vs
  7 days ago, effective VO₂max vs 28 days ago, this week's on-plan %), a countdown to
  your next race, an RPE check-in for any recent unrated session, the coach's latest
  week headline, and a sync-freshness chip (green synced / amber partial or stale /
  red failing — click through for the reason).
- **Overview** — the everything dashboard: recent activities, this week's plan, key stats.
- **Plan** — week-by-week navigation with plan-vs-actual badges on every session and a
  weekly "% on plan" chip; every session opens with its full coaching briefing (why /
  structure / feel / if-it-goes-wrong / cues / fueling) and each week shows its role in
  the plan arc; a **pace-insights chip** proposes accept-one-click pace recalibrations
  when your quality sessions consistently beat (or miss) their windows; edit paces,
  reschedule, add notes, push a week to Garmin — or let the **Monday auto-sync** push
  the next two weeks to your watch automatically.
- **Calendar** — compact month grid (weeks start Monday), with dots colour-coded by
  session type (easy, long, tempo, fast, cross-training) and each day ringed by its
  worst plan-vs-actual band (green on-plan / yellow / orange / red missed); click a day
  to see the session inline (no popups); past days show what you actually did, upcoming
  days show the plan.
- **Activity detail** — opens as a page with **pace / heart-rate / cadence / stride-length**
  charts over time (with an efficient-range band on cadence & stride), an HR-zone
  distribution (with the bpm range per zone), a pace histogram, per-km splits,
  planned-vs-actual, and a Claude-written coaching analysis (with live progress while
  it's generated).
- **HYROX** — import every race from your hyresult.com athlete profile (`paceforge
  hyrox-import-profile <slug>`), then open each race for a full breakdown: per-race
  Overall and Age-group placing, a **field-percentile bar per segment**, a **station
  strengths radar**, a **pacing view** (run-lap fade + cumulative curve), a **roxzone
  transition spotlight**, a **vs-your-other-races** comparison, time split running vs
  stations vs roxzone, every split vs the field & top-3 average, a deterministic coach
  read (weaknesses, pacing mistakes, strengths), an optional Claude-written race review,
  and a cross-race **progression** view (finish-time trend, per-station evolution, and
  your biggest gaps to fix next). Each race also gets a **time-recoverable waterfall**
  ("where your minutes are hiding" vs the cohort average, top-3, or your own PBs), a
  **what-if simulator** (adjust any station, see the projected finish + percentile), a
  **pacing-quality score** with execution flags, a **cumulative gap-to-top-3 curve**, a
  **per-segment standing line**, roxzone "free time" math, and a **target-time split
  calculator**; the progression view adds a **competitiveness trend** (rank-based
  percentile per race), a **career heatmap** (every race × every segment, coloured by
  field percentile — chronic limiters vs one-off bad days at a glance), a **next-race
  projection** (trend across your own race history, or a cohort estimate with none yet),
  a **pacing-strategy effectiveness** read (does even pacing actually correlate with
  better results for *you*, across your career), and **compromised running by station**
  (which transition costs you more running fade than it costs the field, once ordinary
  race-fatigue is subtracted out). All benchmarks are **cohort-adjusted** — compared to
  your own gender/division/age-group field (labelled on the split table), and stations
  more than 60s off the benchmark (or your two weakest) are flagged as training
  priorities. A `--goal HYROX` plan is **running-only** by design (S&C stays outside
  the plan): it biases the quality slots toward **compromised running** — 1 km
  threshold repeats growing toward the race's 8×1 km — plus VO2max and hill work.
- **Events** — add upcoming races/runs (Settings → Upcoming events); they show as a
  countdown on Today and on the Calendar, and the coach rebalances your plan around
  them (taper into races, build between them) gated by your health metrics.
- **Fitness** — the full assessment (below).
- **Settings** — Garmin sync health (last successful sync, failed endpoints, token
  age with an expiry warning), the GitHub token, strength benchmarks, and events.
- Edit the plan, trigger a Sync / Push-to-Garmin, rate a session's effort (RPE 1–10),
  or request a coach analysis straight from the browser via a GitHub fine-grained
  token (stored only in your browser).

## What it measures — Fitness 2.0

Deterministic engines (`paceforge/engine/`) compute a complete athlete assessment from the
Garmin time-series, then a **limiter-ranking** engine turns it into prioritised, readiness-gated
guidance the coach writes up. The Fitness page leads with **Coach's Take** — your top-3 limiters,
each with the metric evidence and a concrete "this week" action.

- **Engine** (`engine/durability.py`): Critical Speed / D′ (+ Critical Power / W′), efficiency-factor
  trend, vVO2max, aerobic decoupling, compromised-run fade, HR-recovery, 80/20 intensity distribution,
  pacing, economy-vs-pace, and an **effective VO₂max** inferred from pace-vs-HR on every ordinary run
  (heat-adjusted, level-calibrated to Garmin, 42-day trend).
- **Pace curves** (`engine/curves.py`): best pace held for every duration (30s–60min) over the last 90
  days, season-over-season, and a **fatigued curve** (efforts starting deep into a session) with a
  per-duration fatigue cost — your compromised-running capacity, quantified. Hot-day paces are
  conditions-adjusted before comparison (`engine/enviro.py`).
- **Load & recovery** (`engine/load.py`): TRIMP load, CTL/ATL/TSB (fitness-fatigue-form), ACWR,
  monotony/strain, injury-spike guardrail, HRV baseline/CV, sleep debt/architecture, an overtraining
  early-warning composite, an **illness watch** (overnight respiration + SpO2 vs baseline, corroborated
  by RHR/HRV), and a daily readiness score — alongside Garmin's native status and running tolerance. Sessions
  without heart-rate data (gym strength, station work) count too, via your **session RPE** rating
  (Foster sRPE, pooled into the same load series).
- **Plan-vs-actual** (`engine/compliance.py`): every session graded against the plan
  (green 80–120% of planned volume / yellow / orange / red missed) with a weekly compliance rollup —
  the badges, chips and calendar rings across the dashboard.
- **Strength / HYROX** (`engine/strength.py`, `hyrox/benchmarks.py`): station percentiles vs **your
  own cohort** (gender/division/age-group), in-race run fade, hybrid (run-vs-strength) balance —
  unlocked by a few one-time benchmarks entered on the Strength tab.

Activity-derived metrics work from existing data immediately; wellness trends fill in over ~6 weeks as
`data/history.jsonl` accumulates a daily snapshot.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/paceforge login        # one-time Garmin auth (handles MFA) → prints GARMIN_TOKEN
```

Run `login` in a **real interactive terminal** — it prompts for your password (hidden) and
an MFA code, so it can't run in a non-interactive shell (a piped CI step or an agent's
`!`-prefixed shell fails with `EOFError`/`No valid Garmin token`).

To enable headless sync, set these GitHub Actions secrets:

| Secret | Purpose |
|--------|---------|
| `PACEFORGE_GARMIN_EMAIL` | Garmin login email |
| `GARMIN_TOKEN` | base64 token printed by `paceforge login` |
| `ACTIONS_PAT` | *(recommended)* fine-grained PAT — repo `paceforge`, **Secrets: Read & Write** |

```bash
.venv/bin/paceforge login | gh secret set GARMIN_TOKEN --repo <owner>/paceforge   # one line
```

**Token self-refresh:** Garmin's OAuth2 token is short-lived, so a stored `GARMIN_TOKEN`
goes stale within days and the daily sync starts failing with `No valid Garmin token`. With
`ACTIONS_PAT` set, `sync.yml` writes the freshly-refreshed token back into the `GARMIN_TOKEN`
secret after every run — **even a failed one**, so one bad sync can't start a stale-token
spiral. Without `ACTIONS_PAT` the refresh step is skipped cleanly and you must re-set
`GARMIN_TOKEN` by hand. The underlying OAuth1 token still expires roughly yearly — when it
does, run `paceforge login` again (login records the date in `data/token-meta.json`, so the
dashboard warns you before the cliff).

**Sync you can trust:** every sync writes `data/sync-status.json` — ok / partial / failed,
which Garmin endpoints failed and why, activity counters, and token age. That file drives the
dashboard's freshness chip and the Settings health panel, so stale numbers never masquerade as
fresh ones. If the scheduled sync fails outright, the workflow opens a `sync-failure` GitHub
issue (which emails you) and closes it automatically on recovery.

See `.env.example` for all variables.

## Usage

```bash
paceforge sync                              # Garmin metrics + activities → data/*.json
paceforge analyze                           # aerobic/economy/load/predictions analysis
paceforge plan --goal MARATHON --date 2026-10-04 --level intermediate
paceforge plan-md                           # regenerate plan.md from data/plan.json
paceforge validate                          # check data/plan.json against the rules
paceforge adapt --dry-run                   # reflow missed sessions + readiness-gate hard work
paceforge recalibrate --delta 0.5           # accepted pace bump: re-target future weeks only
paceforge rpe 7 <activity_id>               # rate a session 1-10 (makes HR-less sessions count)
paceforge push --dry-run                    # preview the week's workouts
paceforge push                              # upload to Garmin
paceforge autosync                          # what Mondays run: push next 2 weeks, clean stale
paceforge hyrox-import-profile <slug>       # import all races from a hyresult.com profile
paceforge hyrox-search "Surname" --gender M # (legacy) results.hyrox.com name search
```

Or just ask Claude: *"sync and review my week"*, *"build my marathon block"*,
*"reschedule Thursday's tempo to Saturday"* — it drives the same commands. The MCP
server (`paceforge-mcp`) exposes the same surface to the Claude desktop app, including
`log_rpe` and `get_fitness`.

## Migrating from the old hosted app

```bash
# Download paceforge.db from Azure (Kudu: /home/data/paceforge.db), then:
python scripts/migrate_from_sqlite.py paceforge.db --email you@example.com
paceforge status                            # confirm your plan + activities came across
```

Once verified, `scripts/decommission_azure.sh` tears down the old App Service + registry.

## Tests

```bash
.venv/bin/pytest tests/ -q
```

## License

MIT
