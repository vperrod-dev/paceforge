# garmin-grafana → PaceForge feature extraction

Date: 2026-08-10 · Source: [arpanghosh8453/garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) (3.4k★, BSD-3-Clause — code reuse OK with attribution) · Local clone: `~/projects/garmin-grafana`

## Verdict

Don't run it — mine it. Its stack (fetcher → InfluxDB → Grafana) duplicates PaceForge's sync + store + portal with zero coaching logic. But its fetcher calls **5 endpoint groups PaceForge doesn't touch**, and two of them fix real gaps in our engine. Everything below is ranked by value to PaceForge.

Baseline for comparison: PaceForge (`src/paceforge/garmin/client.py`) already pulls stats, RHR, training status/load, VO2max, morning training readiness, HRV summary, lactate threshold, endurance/hill score, respiration, SpO2, running tolerance, body composition, body battery, sleep summary, stress summary, race predictions, PRs, activities + splits + HR zones + weather + 200-sample charts, weigh-ins, workout push/pull. So most of garmin-grafana's headline metrics we already have — **as daily aggregates**. The deltas are per-set, per-sample, and historical.

---

## Adopt — ranked

### 1. Per-set strength data (`get_activity_exercise_sets`) — fixes a documented gap ⭐

Our `engine/strength.py` opens with an honesty rule: *"HR and duration from a strength_training session cannot measure strength"* — every strength figure is an HR proxy tagged `confidence="low"`. That's because we never pull set data.

garmin-grafana does (`garmin_fetch.py:789-858`): for each strength activity, `get_activity_exercise_sets(activity_id)` returns per set — exercise **category + name** (user-corrected in Connect, better than FIT — their issue #189), **reps**, **weight** (grams), **duration**, set order, with REST sets filtered out.

For PaceForge this means real tonnage/volume/rep trends feeding `compute_strength_hyrox()`: strength-endurance measured from actual work, not HR; per-exercise progression (sled, lunges, wall balls analogues in gym work); the "data_gaps" list shrinks. Directly serves the Hyrox section.

Also steal their **purge-and-refresh pattern** (`garmin_fetch.py:753`): sets are editable after the fact in Connect, so they delete + rewrite per activity on re-fetch instead of appending. Our JSON store equivalent: overwrite the per-activity record wholesale.

**Effort: S–M.** One new client method + store field + strength.py consumption.

### 2. Sleep intraday + skin temperature — new illness/overtraining signals ⭐

We keep 6 sleep fields (score, duration, 4 stage totals). Their `get_sleep_data` extraction (`garmin_fetch.py:315-500`) shows the same call already returns, unused by us:

- **`avgSkinTempDeviationC`** — overnight skin-temp deviation from baseline; one of the earliest illness/overreaching flags a watch can give. Belongs in the readiness gate for the coach.
- **`restlessMomentsCount`**, **`bodyBatteryChange`** (overnight recharge), **`restingHeartRate`** (sleep-derived), avg/lowest **SpO2 during sleep**, avg sleep stress, awake count.
- Full **sleep-stage timeline** (`sleepLevels` start/end per stage) + restless-moment series — enables the sleep-stage history panel (research item 13) without any new API call.
- **`hrvReadings`** from `get_hrv_data` — the overnight HRV curve, not just `lastNightAvg`. Intra-night HRV trend distinguishes "bad start, recovered by morning" from "suppressed all night".

**Effort: S for the summary fields (same API calls, keep more keys), M for storing timelines.** Highest signal-per-line-of-code in this whole review.

### 3. Panel catalog (Grafana dashboard JSON) — research item 13, confirmed

`Grafana_Dashboard/Garmin-Grafana-Dashboard.json` + the strength dashboard are a field-tested inventory of which long-term views 3.4k users actually want: HRV vs 7d-baseline band, RHR trend, sleep-stage stacked history, body-battery hourly heatmap, stress heatmap, and a strength dashboard (per-exercise volume over time — pairs with #1). Design reference for PaceForge portal panels; render in our UI, not Grafana.

**Effort: S per panel** once #2's data is stored.

### 4. Full-resolution activity data via FIT download

We chart activities from `get_activity_details(maxchart=200)` — 200 samples regardless of duration. They download the original FIT (`download_activity(dl_fmt=ORIGINAL)` → zip → fitparse, `garmin_fetch.py:1029+`, TCX fallback) and get per-second records, plus **cycling dynamics** (seated/standing, power phase, platform offset — `_build_cycling_dynamics_point`) relevant to the Bike section if the pod ever delivers power fields.

Value for us: durability/decoupling analysis (`engine/durability.py`) on real resolution instead of 200 points; optional `KEEP_FIT_FILES` archive gives data portability for free. `fitparse` is a new dependency.

**Effort: M.** Worth it when a concrete analysis is limited by 200 samples — check durability.py's actual needs first.

### 5. Historic bulk import from Garmin Takeout ZIP

`garmin_bulk_importer.py` (528 lines) parses an official Garmin account export (daily stats, sleep, hydration, activity FITs) — years of history with **zero API calls**, no 429s. Our fitness profile looks back 90 days; multi-year HRV/RHR/weight baselines would make the baseline bands in #3 meaningful and improve prognosis calibration.

**Effort: M to adapt output to our JSON store.** One-shot script, not a service.

### 6. Intraday server-side refresh trick (backfill quality)

`POST wellness-service/wellness/epoch/request/{date}` (`garmin_fetch.py:1621-1642`) asks Garmin to regenerate intraday wellness data for an old date before fetching — otherwise back-dates return sparse data. Statuses: SUBMITTED (wait ~10s) / COMPLETE / NO_FILES_FOUND / DENIED (daily cap — they pause 24h!). Only relevant if we backfill via API rather than #5.

**Effort: S.** Keep in the toolbox; don't wire in until a backfill needs it.

## Robustness patterns worth copying (small, anywhere in sync)

- 429 retry loop with wait + **consecutive-500 counter** that aborts a poisoned backfill instead of hammering (`fetch_write_bulk`, `garmin_fetch.py:1692+`).
- Configurable inter-day rate-limit sleep during bulk fetches.
- Idempotent purge-before-rewrite for any Connect-editable data (see #1).

## Skip — and why

| Feature | Why skip |
|---|---|
| InfluxDB + Grafana stack | Parallel infra, second sync of same account, another portal to gate; no coaching value |
| Blood pressure, hydration, solar intensity, lifestyle journal | No device/habit generating the data |
| Fitness age endpoint | Already derived from training status |
| Race predictions, PRs, VO2, readiness, endurance/hill score fetchers | Already have |
| MFA/token login flow | Already have (pinned fork, self-maintaining token) |
| CSV exporter "for AI insights" | Our store is already the AI coach's input |
| Multi-user compose setup | paceforge-users handles athletes our way |
| HomeAssistant watch-battery bridge | Cute; not training data |

## Suggested order

**2 → 1 → 3** (cheap, immediate coach-signal + Hyrox value) — then **4/5** when a concrete analysis demands resolution or history. Each lands as its own small diff: client method → store field → engine/panel consumer.

Attribution when copying: `NOTE: extraction logic adapted from garmin-grafana (BSD-3, © Arpan Ghosh)`.
