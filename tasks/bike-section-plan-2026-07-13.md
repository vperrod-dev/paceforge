# PaceForge Bike — Indoor Cycling Section (Zwift replacement)

**Date:** 2026-07-13 · **Hardware:** Zwift Ride frame + Wahoo KICKR CORE 2 + (any BLE HR strap)

> **BUILD STATUS (2026-07-13, same day):** all 5 phases built and deployed
> (commits 48c9ce1, 5ff62b8, 3fc88b8). Verified: JS selftests (BLE parsing,
> formats, FIT round-trip + fitdecode strict-CRC), 351 pytest, Playwright
> end-to-end in demo mode (mock trainer). **Awaiting hardware:** first real
> KICKR pairing + 10-min ERG hold, Zwift Ride pod handshake/bitmap, real
> intervals.icu/Strava upload. Deliberately minimal: virtual gearing is a flat
> pseudo-grade, suggestion engine is 3 rules, Strava token manual (no OAuth).
**Goal:** replace the Zwift subscription (~€200/yr) with a Bike section inside the PaceForge portal: connect to the trainer from the browser, run structured workouts in ERG mode, record rides, and eventually plan/adapt cycling training the way PaceForge already does for running.

---

## 1. Feasibility verdict — GREEN, browser-only

Everything runs client-side in the existing static PaceForge portal. No backend, no native app, no bridge.

- **KICKR CORE 2 speaks standard BLE FTMS** (Fitness Machine Service `0x1826`) — industry-standard data + control: read power/cadence/speed, write ERG target power and sim grade. Confirmed in DC Rainmaker's CORE 2 review. It also exposes Cycling Power `0x1818` (fallback) and supports 3 concurrent BLE connections.
- **Web Bluetooth works for exactly this.** Chrome/Edge on desktop + Android; HTTPS (GitHub Pages ✓) + one user click per device. Proven in production by **Auuki** (github.com/dvmarinoff/Auuki) — an open-source vanilla-JS PWA doing FTMS ERG control, .ZWO workouts, and .FIT recording in the browser. Multi-device (trainer + HR + Ride pods) is routine.
  - **Hard limit: no Safari/iOS.** Ride from a laptop/Android tablet in front of the bike. Gate the tab on `navigator.bluetooth` with a friendly message.
- **Zwift Ride button pods work outside Zwift.** They pair via BLE to the *app* (left pod relays the right one). The protocol is fully reverse-engineered and **unencrypted** on the Ride generation: proprietary service `0xFC82` (older firmware `00000001-19ca-4651-86e5-fa29dcdd09d1`), handshake = write ASCII `"RideOn"`, then protobuf messages; msg `0x23` = 32-bit button bitmap (0 = pressed), analog levers −100..100. References: Makinolo's protocol write-ups, ajchellew/zwiftplay, OpenBikeControl/bikecontrol.
- **Virtual shifting without Zwift's protocol:** the Zwift Cog is mechanical (single sprocket, no electronics) — "shifting" is just the app changing trainer resistance. We read shift buttons from the Ride pods ourselves, keep a virtual gear number, and scale the FTMS sim-grade/resistance command by gear ratio. In **ERG mode gears are irrelevant** (trainer holds target watts regardless), so structured workouts don't need shifting at all — that's why this can ship late.
- **Risk register:** reverse-engineered Zwift protocol (personal use = low risk; Zwift changed the service UUID once in a Jan-2025 firmware — support both, expect maintenance) · BLE flakiness (auto-reconnect on `gattserverdisconnected` + Screen Wake Lock; Auuki's `ble/` code is the reference) · Auuki is AGPL — **learn from it, don't copy code** into PaceForge.

## 2. What to build (and what to skip)

Distilled from Zwift / TrainerRoad / MyWhoosh / TrainingPeaks Virtual / BreakAway / Auuki survey:

**Copy (training substance):**
- TrainerRoad-style **workout player**: full-workout graph of zone-colored target bars + live power trace + now-cursor; big current/target power, interval countdown, cadence, HR; next-interval preview; text coaching prompts; ERG on/off; **intensity trim ±1%**; pause/skip-interval; live NP/IF/TSS accumulators.
- **.ZWO as the native workout format** → free access to whatsonzwift.com's ~3,100 workouts and TrainerDay's library (TrainerDay also has a personal REST API — potential workout backend). .ERG/.MRC parsers are ~20 lines each, add for completeness.
- **Ramp test** (1-min steps ≈ +6% est-FTP; FTP = 75% of best 1-min power) with accept/apply; FTP history; **Coggan zones** (Z1 <55% … Z7 >150% FTP).
- Formulas: `NP = (mean(rollavg30s(P)^4))^0.25` · `IF = NP/FTP` · `TSS = dur_s·NP·IF/(FTP·3600)·100` · W'bal differential (Froncioni/Skiba) as a live "battery" gauge — v2.
- TrainerRoad **progression levels** (per-zone 1–10, rule-based pass→harder / fail→easier) — the 80% of "adaptive training" — v2/v3.
- **.FIT activity recording** in-browser + upload to **intervals.icu** (free API, gives CTL/ATL/power curves for free) and Strava.

**Skip (game layer):** virtual worlds, avatars, racing, social, RoboPacers. MyWhoosh is free if the itch strikes. No Garmin Connect direct API (partner program) — route via Strava/intervals.icu or the existing garminconnect fork later.

## 3. Where it lands in PaceForge

PaceForge = static SPA (`web/index.html`, vanilla JS, no build step) on GitHub Pages + Python engine + `data/*.json` state written via GitHub Actions `workflow_dispatch`. Fit:

| Concern | Decision |
|---|---|
| UI | New `bike` entry in `NAV` (`web/index.html:1057`), `case 'bike'` in `loadTab` (`:1143`), `renderBike()` view. Live ride loop is 100% client-side. |
| BLE code | New `web/bike/*.js` ES modules (`ftms.js`, `hr.js`, `zwift-ride.js`, `fit-encoder.js`, `player.js`) loaded from `index.html` — keeps the 244KB monolith from doubling. Still no build step. |
| Workout storage | `data/bike/workouts/*.zwo` (git) + paste/upload ZWO in the browser (localStorage cache). |
| Ride persistence | During ride: buffer in memory + localStorage checkpoint every 60s (crash-safe). After ride: download .FIT locally + POST to intervals.icu/Strava direct from browser + optional `save-ride.yml` workflow (clone of `save-rpe.yml` pattern) committing a summary JSON to `data/bike/rides/`. |
| FTP / settings | `data/bike/profile.json` (FTP, FTP history, zones, virtual-gear table) via same write-back pattern; localStorage as working copy. |
| Python models | Extend `models/plan.py`: add `POWER` to `IntensityTarget`, `sport` field on `Workout`, cycling workout types, FTP on plan. Only needed from Phase 4 (plan integration) — the player itself never touches Python. |
| Garmin push | Later: `_CYCLING_SPORT` + `power.zone` target in `garmin/client.py:_to_garmin_step` so bike workouts can also go to the watch/head unit. |

## 4. Phases

### Phase 1 — Connect & ride (the "it's alive" milestone)
- `bike` tab, gated on `navigator.bluetooth`.
- FTMS client: pair KICKR, subscribe Indoor Bike Data `0x2AD2` (power/cadence/speed), Request Control `0x00`, Set Target Power `0x05` (manual ERG slider), Set Sim Params `0x11`.
- HR client (`0x180D`/`0x2A37`).
- Live dashboard: power (3s smoothed), cadence, HR, elapsed, kJ; manual ERG target +/-.
- Wake Lock + auto-reconnect.
- **Exit test: hold 150W ERG from the browser for 10 min without drops.**

### Phase 2 — Structured workouts (Zwift-cancellation milestone)
- ZWO parser (Warmup/Cooldown/SteadyState/IntervalsT/Ramp/FreeRide + textevents) + ERG/MRC parsers.
- Workout player per §2: target-bar graph, live trace, interval engine driving ERG targets, prompts, intensity ±1%, pause/skip, live NP/IF/TSS.
- FTP setting + Coggan zones; ramp test as a built-in workout with auto-FTP-apply.
- Starter library: ~10 curated ZWOs committed to `data/bike/workouts/`.

### Phase 3 — Recording & interop
- In-browser FIT encoder (record msgs: power/HR/cadence/speed streams + lap per interval) — Garmin FIT SDK JS or minimal hand-rolled encoder.
- Post-ride screen: summary (NP/IF/TSS/avg/max), download .FIT, upload to intervals.icu (API key) + Strava (OAuth).
- `save-ride.yml` write-back for ride summaries → rides appear in portal history; feed `activities.json`/matching so bike TSS shows up in PaceForge fitness analytics.

### Phase 4 — Zwift Ride controls & virtual shifting
- Zwift Ride BLE client (`0xFC82` + legacy UUID, RideOn handshake, protobuf `0x23` bitmap decode).
- Map buttons: shift up/down → virtual gear → scaled sim-grade; other buttons → pause, skip interval, intensity ±, ERG toggle (in-ride remote control — big ergonomics win).
- Free-ride sim mode with virtual gears (grade slider or GPX-elevation later).

### Phase 5 — Training plan integration (PaceForge becomes a cycling coach)
- Python model extensions (§3) + a small power-based plan module (parallel to VDOT engine, not a retrofit).
- Progression levels + rule-based "today's suggested ride"; combined run+bike load in fitness analytics (bike TSS ↔ run load).
- Optional: push bike workouts to Garmin (power.zone steps), coach-skill awareness of cycling.

Phases 1–3 = the minimum lovable Zwift replacement. 4 is ergonomics, 5 is where it out-Zwifts Zwift for *training*.

## 5. Open decisions for Victor
1. **Ride device: laptop (decided 2026-07-13)** — Chrome/Edge, the ideal target. No iOS workaround needed.
2. **intervals.icu account** — recommended as the free analytics backend (CTL/W'bal/power curve) instead of building analysis in-portal. Have/want one?
3. **Workout source preference:** curated ZWO library in-repo vs. TrainerDay API as live backend (API key, personal use). Plan assumes in-repo + paste-import first.
4. Cancel Zwift after Phase 2 exit test passes, not before.

## 6. Key references
- Auuki (architecture blueprint, AGPL — inspiration only): github.com/dvmarinoff/Auuki
- Zwift Ride protocol: makinolo.com/blog/2024/07/26/zwift-ride-protocol/ · github.com/ajchellew/zwiftplay · github.com/OpenBikeControl/bikecontrol
- FTMS spec constants: service 0x1826, data 0x2AD2, control point 0x2AD9 (0x00 request, 0x05 ERG watts, 0x11 sim), status 0x2ADA, features 0x2ACC
- ZWO reference: github.com/h4l/zwift-workout-file-reference · library: whatsonzwift.com/workouts · trainerday.com (API: api.trainerday.com)
- KICKR CORE 2: dcrainmaker.com/2025/11/wahoo-kickr-core-2-in-depth-review.html
- Formulas: trainingpeaks.com Coggan NP/IF/TSS article · TrainerRoad ramp-test blog · Skiba W'bal (medium.com/critical-powers)
