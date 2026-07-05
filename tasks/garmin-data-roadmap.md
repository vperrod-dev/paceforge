# Garmin data — what else is worth pulling

Audit of `garminconnect` endpoints beyond what `garmin/client.py` already fetches
(training status/readiness, VO2max, HRV, lactate threshold, endurance score,
body battery, sleep, stress, race predictions, personal records, weight,
per-activity splits/HR-zones/weather/time-series, structured-workout push).
Ranked by value to `engine/load.py` (CTL/ATL/TSB/readiness) and
`engine/durability.py` (effective VO2max/limiters) vs. implementation cost.

**Shipped from this pass:** morning training readiness (`get_morning_training_readiness`,
fixes a latent bug — the old code could grab a post-nap reading instead of the
AFTER_WAKEUP_RESET one) and Hill Score (`get_hill_score`, a new uphill-running
composite independent of the flat-ground endurance score).

## Next up

1. **Race-prediction trend** (`get_race_predictions(startdate, enddate)`) — the
   client only ever fetches the latest snapshot. A weekly/monthly trend of
   Garmin's own predicted marathon/half/10K/5K time is a genuine fitness
   trajectory signal nothing else in the codebase tracks. Needs a new
   `history.jsonl`-style series (one row isn't enough — it's the *slope* that
   matters), so it's a schema addition, not a one-line fetch. Moderate effort,
   high value.

2. **Running tolerance** (`get_running_tolerance(startdate, enddate, aggregation)`)
   — Garmin's own load-absorption/injury-risk trend. Conceptually overlaps
   with the CTL/ATL/TSB/ACWR model `engine/load.py` already computes from
   scratch; worth adding as a cross-check against our own numbers rather than
   a replacement. Needs new range-series storage. Moderate effort, moderate
   value.

3. **Per-second FIT data** (`download_activity(..., dl_fmt=ORIGINAL)` +
   `garminconnect/fit.py`) — full-resolution power/HR/cadence vs. the current
   200-point downsample from `get_activity_details`. Would sharpen
   `engine/curves.py` pace-duration curves at the short end (sub-30s) and give
   real per-rep detail on HYROX station splits. Heaviest lift here: binary
   download, FIT parsing, new per-activity storage — worth it only if the
   200-point curves prove too coarse in practice.

## Looked at, not worth it yet

- **Body Battery events** (`get_body_battery_events`) — richer than the
  current current/high/low daily snapshot, but that snapshot already carries
  what `load.py`'s readiness composite needs; event-level detail is a
  presentation nicety, not a new signal.
- **All-day stress detail** (`get_all_day_stress`) — same story: the stored
  avg/high/low already feeds the composite; a per-minute timeline needs new
  time-series storage for no analytical gain.
- **Dedicated fitness-age endpoint** (`get_fitnessage_data`) — redundant,
  `fitness_age` is already read for free out of `get_training_status`'s
  `mostRecentVO2Max.generic.fitnessAge`.
- **Lactate-threshold trend** — the installed `garminconnect` version's
  `get_lactate_threshold` only supports `latest=True`; no date-range variant
  exists to pull a trend from.
