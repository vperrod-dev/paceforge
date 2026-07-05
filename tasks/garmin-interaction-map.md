# Garmin interaction map — every way PaceForge can talk to Garmin

Full research pass (2026-07-05) over all Garmin interaction surfaces, ranked by
what each unlocks for HYROX training. Companion to `garmin-data-roadmap.md`
(endpoint-level pull audit).

## Surfaces in use

- **Unofficial `garminconnect` pull** — ~80% of the high-value wellness/activity
  surface already synced (readiness, HRV, sleep, body battery, stress, VO2max,
  LT, endurance + hill score, race predictor, PRs, running-dynamics summaries,
  downsampled activity series, respiration/SpO2/running-tolerance as of this
  pass). Client is a pinned **fork**
  (`diegoscarabelli/python-garminconnect@feat/widget-cffi-login-strategy`,
  curl_cffi MFA login) — upstream-0.3.6 features (STRENGTH/HIIT workout push,
  exercise-set setters, self-healing token strategies) require a fork rebase,
  not a pip bump.
- **Structured-workout push + calendar scheduling** — `push_plan_week` /
  `schedule_workout`; scheduled workouts surface in the watch training calendar
  and morning report automatically. HYROX sessions upload as
  `fitness_equipment` with automatic running fallback.

## Surfaces researched, not yet used

| Surface | Feasibility | Effort | Unlocks |
|---|---|---|---|
| **Connect IQ data field** (Monkey C; sideload `.prg` over USB, no store approval; System 8 devices need SDK ≥ 7.4.3 builds) | Proven — ROXZONE / Hyrox Partner exist; none close the loop with a planning tool | M | HYROX race mode on the wrist: lap-press station/run/roxzone tracking, live target-vs-actual deltas fed from PaceForge-generated settings |
| **FIT developer fields** (`Toybox.FitContributor`, per-lap `station_id`/`target_s`/`delta_s`) | Sideloaded apps DO write dev fields into the FIT file; only GC *chart display* needs store publication — irrelevant since PaceForge parses FIT itself | S on top of the data field | Race results flow back structured, zero manual tagging — closes plan → race → analysis |
| **Per-second FIT pull** (`download_activity(ORIGINAL)` + `fitdecode`) | No approval needed | L | 1-second GCT/stride/power decay under fatigue — the core "compromised running" measurement; sharpens pace curves sub-30s |
| **USB FIT workout sideload** (FIT SDK workout cookbook → `GARMIN/NewFiles/`) | Fully supported, laptop-side | S | Insurance against unofficial-API breakage; workout types the GC builder can't express (no calendar/morning-report integration though) |
| **Race event / Primary Race push** | No known endpoint — would need reverse-engineering GC web calls; nobody has published one | M, breakage risk | Countdown glance + race-aware daily suggestions driven from PaceForge |
| **BLE HR broadcast reader** (standard BLE HR profile; watch broadcasts HR + pace/cadence during runs) | Trivial (Web Bluetooth / `bleak`), no Garmin account involved | S | Live HR pane for indoor sim sessions |
| **LiveTrack scraping** (JSON endpoints behind the LiveTrack session page; OSS prior art) | Unofficial, session URL from the LiveTrack email | M | Spectator/coach live view — low athlete value vs the wrist |
| **CIQ companion app** (Communications / Mobile Companion SDK) | Free SDK | L | Only path for watch-computed live metrics off-device; build only if a live phone dashboard becomes a real need |
| **Official Training/Courses API** | Connect Developer Program **on hold** for new signups + business-only | blocked | Nothing beyond the unofficial push for a single athlete |
| **PacePro push** | Undocumented; course-based road-race feature | skip | Nothing for indoor HYROX |

## Recommended build order

1. **Done:** overnight respiration + SpO2 → illness watch;
   running tolerance cross-check; morning readiness + hill score (#45).
2. **Done — Typed splits** (`get_activity_typed_splits`) — recorded HYROX sims/races
   auto-segment into run/station/roxzone via `engine/segments.py` (`fitness()` →
   `hyrox_segments`, Strength-tab card); classified by run/walk/stand typing, no
   manual entry.
3. **Exercise sets** (`get_activity_exercise_sets`) — strength tonnage into the
   load model (today strength is sRPE-only); station-strength progression.
4. **USB FIT workout export** (`paceforge export-fit`) — cheap push fallback.
5. **Fork rebase onto upstream 0.3.6** — STRENGTH/HIIT push + self-healing
   tokens (less GARMIN_TOKEN pain). Verify the cffi MFA strategy survives.
6. **Per-second FIT pipeline** — flagship durability/fatigue measurement.
7. **Connect IQ race data field + FitContributor** — separate subproject
   (Monkey C); turns PaceForge into a race-day tool. Sideload only.
