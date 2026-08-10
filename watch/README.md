# PaceForge watch fields (2 data screens)

**Two Connect IQ data fields** — Garmin allows max 2 CIQ fields per activity
profile, and data fields can't paginate internally, so each gets its own
1-field data screen; swipe (or UP/DOWN) between them mid-run:

1. **PaceForge Coach** (`build/PaceForgeField-*.prg`) — the workout screen:
   pace-arc gauge + verdict + step stats + BIG heart rate colored by zone,
   with a bottom arc showing your position across your 5 HR zones.
2. **PaceForge Form** (`form/build/PaceForgeForm-*.prg`) — the form screen:
   cadence-arc gauge (teal 170–180 spm target), BIG cadence + BIG stride,
   pace/HR footer.

Sideload BOTH .prg files to `/GARMIN/APPS/`, then add each as the only field
on its own 1-field data screen. HR zones come from your Garmin user profile
(Settings → User Profile → Heart Rate Zones → Running).

# PaceForge Coach Field

Full-screen Garmin Connect IQ **data field** for the fēnix 7X / 7X Pro (280x280 MIP, CIQ API 5.2).

During a native Run activity executing a structured workout it shows:

- current step name (top) + step notes (one line, truncated)
- big live pace (min/km), colored by drift vs the step's pace band:
  **green** inside the band, **amber** within 5% outside, **red** beyond
- target pace band (fast-slow, /km)
- time or distance remaining in the current step ("LAP to end step" for open steps)
- next-step preview footer (name, band, duration)

With no workout active: big pace + HR + distance.

No network use, no timers — everything is computed in `compute()` (1 Hz) and drawn in `onUpdate()`.

## Layout on the watch

Add it as the **only field on a 1-field data screen** to get the full-screen layout:
Run activity → hold **UP** → Run Settings → Data Screens → Add New → 1 field →
select **Connect IQ Fields → PaceForge Coach**. Garmin allows max **2 CIQ data fields**
per activity profile.

## Files

```
watch/
  manifest.xml                  # type=datafield, min API 3.2.0, fenix7x + fenix7xpro
  monkey.jungle
  source/PaceForgeFieldApp.mc   # AppBase entry
  source/PaceForgeFieldView.mc  # all logic + drawing
  resources/strings/strings.xml
  resources/drawables/drawables.xml + launcher_icon.png
  build/PaceForgeField-fenix7x.prg     # prebuilt, signed, ready to sideload
  build/PaceForgeField-fenix7xpro.prg
```

## Build (already verified on this VM)

Toolchain installed on this VM — no Garmin login was needed:

- SDK: `~/tools/connectiq-sdk-9.2.0` (from the public manifest
  https://developer.garmin.com/downloads/connect-iq/sdks/sdks.json — direct zip download)
- Java: `openjdk-17-jre-headless` (monkeyc is a Java jar)
- Device definitions: `~/.Garmin/ConnectIQ/Devices/{fenix7x,fenix7xpro}` (API 5.2.0).
  Note: Garmin normally gates these behind SDK-manager login; these were sourced from a
  public repo that vendors them. To refresh them officially: install
  https://github.com/lindell/connect-iq-sdk-manager-cli then
  `connect-iq-sdk-manager login && connect-iq-sdk-manager device download --manifest=manifest.xml`.
- Developer key: `~/.Garmin/ConnectIQ/developer_key.der` (throwaway, generated for sideload
  signing; only matters if you upload to the CIQ store, in which case keep the key stable).
  To regenerate:

  ```sh
  openssl genrsa -out developer_key.pem 4096
  openssl pkcs8 -topk8 -inform PEM -outform DER -in developer_key.pem \
      -out developer_key.der -nocrypt
  ```

Compile (from `watch/`):

```sh
~/tools/connectiq-sdk-9.2.0/bin/monkeyc \
    -o build/PaceForgeField-fenix7x.prg \
    -f monkey.jungle \
    -y ~/.Garmin/ConnectIQ/developer_key.der \
    -d fenix7x -w -r
```

Repeat with `-d fenix7xpro` for the Pro. Both targets build clean with `-w`
(zero warnings) on SDK 9.2.0. Release `.prg` is ~10 KB against a 256 KB
datafield budget on fenix7x.

Older SDKs won't work: the current fenix7x device files declare API 5.2.0, which
requires SDK >= 9.x (8.2.3 tops out at API 5.1.1 and refuses the device).

## Sideload via USB

1. Plug the fēnix 7X in via USB (it mounts as mass storage; on Linux it's MTP —
   `gio mount -li` / a file manager, or use Garmin Express on Win/Mac).
2. Copy `build/PaceForgeField-fenix7x.prg` into the watch's `/GARMIN/APPS/` folder.
3. Eject/unplug. The field appears under Connect IQ Fields immediately.
4. Add it to a 1-field data screen (see "Layout on the watch" above).
5. To remove: delete the `.prg` from `/GARMIN/APPS/`.

Sideloaded fields signed with any developer key run fine; store distribution
would additionally need an app-store upload signed with the same key.

## API notes / caveats (from docs + RunPowerWorkout source)

- `Activity.getCurrentWorkoutStep()` / `getNextWorkoutStep()` (API 3.2.0) return
  `WorkoutStepInfo` or **null** (null = no structured workout running, or no next step).
  The code also guards with `has` + `try/catch` — docs mention the call can throw
  on unsupported configurations.
- `WorkoutStepInfo.step` is either a `WorkoutStep` or, inside repeat blocks, a
  `WorkoutIntervalStep {activeStep, restStep, repetitionNumber}` — we unwrap to
  `activeStep` via a `has :activeStep` check.
- Speed targets: `targetValueLow/High` with `targetType == WORKOUT_STEP_TARGET_SPEED` (0).
  Units are m/s on current firmware, but some firmwares hand back raw FIT values
  (mm/s, scale 1000) — `normSpeed()` treats anything > 50 as mm/s. (For comparison,
  power targets carry a +1000 FIT offset — RunPowerWorkout subtracts 1000.)
- `durationType`: TIME(0) → `durationValue` in seconds; DISTANCE(1) → meters;
  OPEN(5) → ends on LAP press. HR/calorie/power duration types are not displayed.
- Step-elapsed time/distance are not exposed directly; we snapshot `timerTime` /
  `elapsedDistance` in the `onWorkoutStepComplete()` / `onWorkoutStarted()` /
  `onTimerReset()` DataField callbacks (same pattern as RunPowerWorkout).
- `timerTime` (ms, pauses with the timer) drives step time, so pauses don't eat
  step-remaining time.
