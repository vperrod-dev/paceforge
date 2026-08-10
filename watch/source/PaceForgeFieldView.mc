using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Math;
using Toybox.UserProfile;
using Toybox.Activity;
using Toybox.Lang;
using Toybox.Communications;
using Toybox.Application;

// PaceForge Coach Field — full-screen (single-field layout) run data field.
// With an active structured workout: step name + notes, target pace band,
// live pace colored by drift vs the band, time/distance remaining in the
// step, and a next-step preview. Without a workout: pace / HR / distance.
class PaceForgeFieldView extends WatchUi.DataField {

    // live values, refreshed each compute()
    hidden var curSpeed = null;   // m/s or null
    hidden var curHr = null;
    hidden var curCad = null;     // steps/min or null
    hidden var dist = null;       // meters or null
    hidden var timerSec = 0;      // running timer, seconds

    // current-step state
    hidden var haveWorkout = false;
    hidden var stepName = "";
    hidden var stepNotes = null;
    hidden var lowSpeed = null;   // band, m/s (low = slow bound)
    hidden var highSpeed = null;  // band, m/s (high = fast bound)
    hidden var remainText = "";
    hidden var nextText = null;

    // step boundary trackers (reset on step change)
    hidden var stepStartSec = 0;
    hidden var stepStartDist = 0.0;

    // stimulus: zone-weighted TRIMP accumulated on-watch (minutes x zone
    // weight 1..5), shown as % of the coach's planned_trimp when present
    hidden var plannedTrimp = null;      // from watch-targets; null = show TIME
    hidden var trimpWeightedSec = 0.0;   // sum(seconds x zone weight)
    hidden var lastTimerSec = 0;

    // HR drift: efficiency factor (speed/HR) baseline = first 5 min of a
    // steady step, compared to the rolling last 3 min
    hidden var driftStartSec = 0;
    hidden var prevLowSpeed = null;
    hidden var prevHighSpeed = null;
    hidden var efBaseSum = 0.0;
    hidden var efBaseN = 0;
    hidden var efBuf;                    // 180-sample ring (last 3 min)
    hidden var efBufIdx = 0;
    hidden var efBufN = 0;
    hidden var efBufSum = 0.0;
    hidden var driftPct = null;          // Number, null = no alert

    function initialize() {
        DataField.initialize();
        efBuf = new [180];
        var pt = Application.Storage.getValue("planned_trimp");
        if (pt != null) {
            plannedTrimp = pt.toFloat();
        }
        fetchTargets();
    }

    // Pull the coach's targets through the phone (same fetch the Form field
    // does). Fire-and-forget: offline -> cached/absent, the run is unaffected.
    hidden function fetchTargets() {
        if (!(Communications has :makeWebRequest) || TARGETS_URL.equals("")) {
            return;
        }
        try {
            Communications.makeWebRequest(TARGETS_URL, null,
                { :method => Communications.HTTP_REQUEST_METHOD_GET,
                  :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON },
                method(:onTargets));
        } catch (e) {
        }
    }

    function onTargets(code, data) {
        if (code != 200 || !(data instanceof Lang.Dictionary)) {
            return;
        }
        if (data["planned_trimp"] != null) {
            plannedTrimp = data["planned_trimp"].toFloat();
            Application.Storage.setValue("planned_trimp", plannedTrimp);
        } else {
            // no planned stimulus today -> fall back to the TIME column
            plannedTrimp = null;
            Application.Storage.deleteValue("planned_trimp");
        }
    }

    // ---- activity event callbacks -------------------------------------

    function onWorkoutStarted() {
        resetStepStart();
    }

    function onWorkoutStepComplete() {
        resetStepStart();
    }

    function onTimerReset() {
        stepStartSec = 0;
        stepStartDist = 0.0;
        trimpWeightedSec = 0.0;
        lastTimerSec = 0;
        resetDrift();
        driftStartSec = 0;
    }

    hidden function resetStepStart() {
        stepStartSec = timerSec;
        var info = Activity.getActivityInfo();
        if (info != null && info.elapsedDistance != null) {
            stepStartDist = info.elapsedDistance;
        } else {
            stepStartDist = 0.0;
        }
        resetDrift();
    }

    hidden function resetDrift() {
        driftStartSec = timerSec;
        efBaseSum = 0.0;
        efBaseN = 0;
        efBufIdx = 0;
        efBufN = 0;
        efBufSum = 0.0;
        driftPct = null;
    }

    // ---- compute (1 Hz) ------------------------------------------------

    function compute(info) {
        curSpeed = (info != null) ? info.currentSpeed : null;
        curHr = (info != null) ? info.currentHeartRate : null;
        curCad = (info != null) ? normCadence(info.currentCadence) : null;
        dist = (info != null) ? info.elapsedDistance : null;
        var tt = (info != null) ? info.timerTime : null;
        if (tt != null) {
            timerSec = tt / 1000;
        }

        var ws = null;
        if (Activity has :getCurrentWorkoutStep) {
            // Docs allow this to throw on unsupported configurations; also
            // the capability can exist while the value is null (no workout).
            try {
                ws = Activity.getCurrentWorkoutStep();
            } catch (e) {
                ws = null;
            }
        }

        haveWorkout = (ws != null);
        lowSpeed = null;
        highSpeed = null;
        remainText = "";
        nextText = null;
        stepNotes = null;
        stepName = "";

        if (ws == null) {
            tick();
            return null;
        }

        stepName = (ws.name != null) ? ws.name : intensityLabel(ws.intensity);
        if (ws.notes != null && !ws.notes.equals("")) {
            stepNotes = ws.notes;
        }

        var st = coreStep(ws.step);
        if (st != null) {
            if (st.targetType != null
                && st.targetType == Activity.WORKOUT_STEP_TARGET_SPEED) {
                var lo = normSpeed(st.targetValueLow);
                var hi = normSpeed(st.targetValueHigh);
                // keep the band ordered: low = slow bound, high = fast bound
                if (lo != null && hi != null && lo > hi) {
                    var tmp = lo;
                    lo = hi;
                    hi = tmp;
                }
                lowSpeed = lo;
                highSpeed = hi;
            }
            remainText = remainingLabel(st);
        }

        var nx = null;
        if (Activity has :getNextWorkoutStep) {
            try {
                nx = Activity.getNextWorkoutStep();
            } catch (e2) {
                nx = null;
            }
        }
        if (nx != null) {
            nextText = nextLabel(nx);
        }

        tick();
        return null;
    }

    // ---- per-tick accumulation (stimulus TRIMP + HR drift) ---------------

    // Runs once per compute(); only accumulates while the timer advances.
    hidden function tick() {
        // a pace-band change (incl. workout start/end) restarts the drift
        // baseline — steadiness is measured from the last band change
        if (lowSpeed != prevLowSpeed || highSpeed != prevHighSpeed) {
            prevLowSpeed = lowSpeed;
            prevHighSpeed = highSpeed;
            resetDrift();
        }

        var dt = timerSec - lastTimerSec;
        lastTimerSec = timerSec;
        if (dt <= 0 || dt > 10) {   // paused, reset, or a stale gap
            return;
        }

        if (curHr != null && curHr > 0) {
            var z = zones();
            var wgt = (z != null && z.size() >= 6) ? zoneIndex(curHr, z) + 1 : 1;
            trimpWeightedSec += dt * wgt;
        }

        if (curSpeed != null && curSpeed > 0.5 && curHr != null && curHr > 100) {
            var ef = curSpeed / curHr;   // efficiency factor
            if (timerSec - driftStartSec <= 300) {
                efBaseSum += ef;
                efBaseN += 1;
            }
            if (efBufN < 180) {
                efBufN += 1;
            } else {
                efBufSum -= efBuf[efBufIdx];
            }
            efBuf[efBufIdx] = ef;
            efBufSum += ef;
            efBufIdx = (efBufIdx + 1) % 180;
        }

        updateDrift();
    }

    // Conservative: >= 8 min into the steady step, >= 3 of the first 5 min and
    // >= 2 of the last 3 min with valid samples, and EF down > 6% vs baseline.
    hidden function updateDrift() {
        driftPct = null;
        if (timerSec - driftStartSec < 480) {
            return;
        }
        if (efBaseN < 180 || efBufN < 120 || efBaseSum <= 0) {
            return;
        }
        var ratio = (efBufSum / efBufN) / (efBaseSum / efBaseN);
        if (ratio < 0.94) {
            driftPct = ((1.0 - ratio) * 100.0 + 0.5).toNumber();
        }
    }

    // ---- workout step helpers -------------------------------------------

    // Repeat blocks surface as WorkoutIntervalStep {activeStep, restStep};
    // use the active portion for targets/duration.
    hidden function coreStep(step) {
        if (step == null) {
            return null;
        }
        if (step has :activeStep) {
            return (step.activeStep != null) ? step.activeStep : null;
        }
        return step;
    }

    // Target speeds arrive as m/s on most firmwares but as mm/s (raw FIT,
    // scale 1000) on some. No running target exceeds 50 m/s, so treat
    // anything above that as mm/s.
    hidden function normSpeed(v) {
        if (v == null) {
            return null;
        }
        var f = v.toFloat();
        if (f > 50.0) {
            f = f / 1000.0;
        }
        return (f > 0.0) ? f : null;
    }

    // Some firmwares report running cadence as strides/min (~85), others as
    // steps/min (~170). Nobody runs below 120 spm mid-workout — double the
    // low reading.
    hidden function normCadence(c) {
        if (c == null || c == 0) {
            return null;
        }
        var n = c.toNumber();
        return (n < 120) ? n * 2 : n;
    }

    // Stride length in meters, derived (the CIQ API does not expose it):
    // speed [m/s] / steps-per-second. Matches Garmin's own stride number.
    hidden function strideStr() {
        if (curSpeed == null || curSpeed < 0.3 || curCad == null || curCad < 60) {
            return "-.--";
        }
        return (curSpeed * 60.0 / curCad).format("%.2f");
    }

    hidden function metricsLine() {
        var hr = (curHr != null) ? curHr.format("%d") : "--";
        var cad = (curCad != null) ? curCad.format("%d") : "---";
        return hr + " bpm   " + cad + " spm   " + strideStr() + " m";
    }

    hidden function remainingLabel(st) {
        var dt = st.durationType;
        var dv = st.durationValue;
        if (dt == null) {
            return "";
        }
        if (dt == Activity.WORKOUT_STEP_DURATION_TIME) {
            if (dv != null) {
                var left = dv - (timerSec - stepStartSec);
                if (left < 0) {
                    left = 0;
                }
                return fmtTime(left) + " left";
            }
        } else if (dt == Activity.WORKOUT_STEP_DURATION_DISTANCE) {
            if (dv != null && dist != null) {
                var leftM = dv - (dist - stepStartDist);
                if (leftM < 0) {
                    leftM = 0;
                }
                return fmtDist(leftM) + " left";
            }
        } else if (dt == Activity.WORKOUT_STEP_DURATION_OPEN) {
            return "LAP to end step";
        }
        return "";
    }

    hidden function nextLabel(nx) {
        var s = "Next: ";
        s += (nx.name != null) ? nx.name : intensityLabel(nx.intensity);
        var st = coreStep(nx.step);
        if (st == null) {
            return s;
        }
        if (st.targetType != null
            && st.targetType == Activity.WORKOUT_STEP_TARGET_SPEED) {
            var lo = normSpeed(st.targetValueLow);
            var hi = normSpeed(st.targetValueHigh);
            if (lo != null && hi != null) {
                if (lo > hi) {
                    var tmp = lo;
                    lo = hi;
                    hi = tmp;
                }
                s += " " + paceStr(hi) + "-" + paceStr(lo);
            }
        }
        if (st.durationType != null && st.durationValue != null) {
            if (st.durationType == Activity.WORKOUT_STEP_DURATION_TIME) {
                s += " " + fmtTime(st.durationValue);
            } else if (st.durationType == Activity.WORKOUT_STEP_DURATION_DISTANCE) {
                s += " " + fmtDist(st.durationValue);
            }
        }
        return s;
    }

    hidden function intensityLabel(intensity) {
        if (intensity == Activity.WORKOUT_INTENSITY_WARMUP) {
            return "Warm up";
        } else if (intensity == Activity.WORKOUT_INTENSITY_COOLDOWN) {
            return "Cool down";
        } else if (intensity == Activity.WORKOUT_INTENSITY_REST) {
            return "Rest";
        } else if (intensity == Activity.WORKOUT_INTENSITY_RECOVERY) {
            return "Recovery";
        } else if (intensity == Activity.WORKOUT_INTENSITY_INTERVAL) {
            return "Interval";
        }
        return "Run";
    }

    // ---- formatting ------------------------------------------------------

    // m/s -> "m:ss" per km; null/near-standstill -> "--:--"
    hidden function paceStr(speed) {
        if (speed == null || speed < 0.3) {
            return "--:--";
        }
        var secPerKm = (1000.0 / speed).toNumber();
        if (secPerKm > 5999) { // cap at 99:59
            secPerKm = 5999;
        }
        return (secPerKm / 60).format("%d") + ":" + (secPerKm % 60).format("%02d");
    }

    hidden function fmtTime(sec) {
        var s = sec.toNumber();
        if (s >= 3600) {
            return (s / 3600).format("%d") + ":" + ((s % 3600) / 60).format("%02d")
                + ":" + (s % 60).format("%02d");
        }
        return (s / 60).format("%d") + ":" + (s % 60).format("%02d");
    }

    hidden function fmtDist(meters) {
        var m = meters.toFloat();
        if (m >= 1000.0) {
            return (m / 1000.0).format("%.2f") + " km";
        }
        return m.toNumber().format("%d") + " m";
    }

    // ---- drawing ---------------------------------------------------------
    // Runna-style: white face, top pace-arc gauge (teal band, red edges,
    // needle at current pace), band text, huge pace, verdict word, labeled
    // stat columns, HR/cadence/stride row, next-step footer.

    hidden var TEAL = 0x00AA88;
    hidden var RED = 0xFF5544;
    hidden var GREY = 0x555555;
    // Garmin's conventional zone colors: Z1 grey, Z2 blue, Z3 green, Z4 orange, Z5 red
    hidden var ZONE_COLORS = [0x999999, 0x3B8AD8, 0x00AA55, 0xFF8800, 0xE0402F];
    hidden var hrZones = null;   // [z1 floor, z1 top, z2 top, z3 top, z4 top, z5 top]

    hidden function zones() {
        if (hrZones == null) {
            try {
                hrZones = UserProfile.getHeartRateZones(UserProfile.HR_ZONE_SPORT_RUNNING);
            } catch (e) {
                hrZones = [];
            }
        }
        return hrZones;
    }

    hidden function zoneIndex(hr, z) {   // 0-based zone for a heart rate
        for (var i = 5; i >= 2; i--) {
            if (hr > z[i - 1]) {
                return i - 1;
            }
        }
        return 0;
    }

    function onUpdate(dc) {
        // Runna forces a light face regardless of system theme — daylight
        // legibility on MIP; we follow the reference look.
        var bg = Graphics.COLOR_WHITE;
        var fg = Graphics.COLOR_BLACK;
        var dim = Graphics.COLOR_DK_GRAY;

        dc.setColor(fg, bg);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        if (haveWorkout) {
            drawWorkout(dc, w, h, cx, fg, dim);
        } else {
            drawBasics(dc, w, h, cx, fg, dim);
        }
    }

    // Map a pace (sec/km) onto the top arc: the band occupies the middle
    // [0.30, 0.70] of the gauge (Runna-proportioned), red zones the edges.
    hidden function paceFrac(sec, slowSec, fastSec) {
        var f = 0.30 + 0.40 * (slowSec - sec) / (slowSec - fastSec);
        if (f < 0.0) { f = 0.0; }
        if (f > 1.0) { f = 1.0; }
        return f;
    }

    // Arc runs over the top of the round face: 150deg (left) -> 30deg (right).
    hidden function fracDeg(f) {
        return 150.0 - f * 120.0;
    }

    hidden function drawPaceArc(dc, w, h, cx) {
        if (lowSpeed == null || highSpeed == null) {
            return;
        }
        var cy = h / 2;
        var r = (w / 2) - 8;
        var slowSec = 1000.0 / lowSpeed;    // band slow bound, sec/km
        var fastSec = 1000.0 / highSpeed;   // band fast bound, sec/km
        var f1 = paceFrac(slowSec, slowSec, fastSec);  // band start
        var f2 = paceFrac(fastSec, slowSec, fastSec);  // band end

        dc.setPenWidth(13);
        // too-slow segment (left, red)
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(0.0), fracDeg(f1));
        // in-band segment (teal)
        dc.setColor(TEAL, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(f1), fracDeg(f2));
        // too-fast segment (right, red)
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(f2), fracDeg(1.0));
        dc.setPenWidth(1);

        // needle: grey triangle just inside the arc at the current pace
        if (curSpeed != null && curSpeed >= 0.3) {
            var f = paceFrac(1000.0 / curSpeed, slowSec, fastSec);
            var a = fracDeg(f) * Math.PI / 180.0;
            var tipR = r - 14.0;
            var baseR = r - 26.0;
            var spread = 4.0 * Math.PI / 180.0;
            var tip = [cx + tipR * Math.cos(a), cy - tipR * Math.sin(a)];
            var b1 = [cx + baseR * Math.cos(a - spread), cy - baseR * Math.sin(a - spread)];
            var b2 = [cx + baseR * Math.cos(a + spread), cy - baseR * Math.sin(a + spread)];
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            dc.fillPolygon([tip, b1, b2]);
        }
    }

    hidden function verdict() {
        if (curSpeed == null || curSpeed < 0.3
            || lowSpeed == null || highSpeed == null) {
            return null;
        }
        if (curSpeed >= lowSpeed && curSpeed <= highSpeed) {
            return "GOOD PACE";
        }
        return (curSpeed < lowSpeed) ? "TOO SLOW" : "TOO FAST";
    }

    hidden function drawWorkout(dc, w, h, cx, fg, dim) {
        drawPaceArc(dc, w, h, cx);

        var hasBand = (lowSpeed != null && highSpeed != null);

        // band text (or the step name when there is no pace target)
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        var top = hasBand
            ? paceStr(highSpeed) + " - " + paceStr(lowSpeed) + "/KM"
            : fitText(dc, stepName, Graphics.FONT_SMALL, w * 0.62);
        dc.drawText(cx, h * 0.135, Graphics.FONT_SMALL, top,
            Graphics.TEXT_JUSTIFY_CENTER);

        // huge current pace (black — the arc + verdict carry the color)
        dc.drawText(cx, h * 0.20, Graphics.FONT_NUMBER_HOT, paceStr(curSpeed),
            Graphics.TEXT_JUSTIFY_CENTER);

        // verdict word (teal/red), or step name under the pace when banded;
        // an active HR-drift alert shares the line, alternating each second
        var v = verdict();
        var drift = (driftPct != null)
            ? "DRIFT +" + driftPct.format("%d") + "%" : null;
        if (drift != null && (v == null || timerSec % 2 == 1)) {
            dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.455, Graphics.FONT_TINY, drift,
                Graphics.TEXT_JUSTIFY_CENTER);
        } else if (v != null) {
            dc.setColor(v.equals("GOOD PACE") ? TEAL : RED, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.455, Graphics.FONT_TINY, v,
                Graphics.TEXT_JUSTIFY_CENTER);
        } else if (hasBand) {
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.455, Graphics.FONT_TINY,
                fitText(dc, stepName, Graphics.FONT_TINY, w * 0.7),
                Graphics.TEXT_JUSTIFY_CENTER);
        }
        if (hasBand && v != null) {
            // step name in small caps between verdict and stats
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.535, Graphics.FONT_XTINY,
                fitText(dc, stepName, Graphics.FONT_XTINY, w * 0.8),
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        // three labeled stat columns: step-left / load-or-time / distance.
        // LOAD = live zone-weighted TRIMP as % of the coach's planned_trimp;
        // without a planned value the column stays TIME as before.
        var midVal = fmtTime(timerSec);
        var midLab = "TIME";
        if (plannedTrimp != null && plannedTrimp > 0) {
            var pct = trimpWeightedSec / 60.0 / plannedTrimp * 100.0;
            if (pct > 999.0) {
                pct = 999.0;
            }
            midVal = pct.toNumber().format("%d") + "%";
            midLab = "LOAD";
        }
        var xs = [w * 0.26, w * 0.5, w * 0.74];
        var vals = [
            remainText.equals("") ? "--" : stripLeft(remainText),
            midVal,
            (dist != null) ? fmtDist(dist) : "0 m",
        ];
        var labs = ["STEP LEFT", midLab, "DISTANCE"];
        for (var i = 0; i < 3; i++) {
            dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
            dc.drawText(xs[i], h * 0.615, Graphics.FONT_SMALL, vals[i],
                Graphics.TEXT_JUSTIFY_CENTER);
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(xs[i], h * 0.695, Graphics.FONT_XTINY, labs[i],
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        // heart rate, big, colored by zone (cadence/stride live on the
        // companion "PaceForge Form" field — second data screen)
        drawHr(dc, w, h, cx, fg);

        // next-step footer
        if (nextText != null) {
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.845, Graphics.FONT_XTINY,
                fitText(dc, nextText, Graphics.FONT_XTINY, w * 0.58),
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        drawHrArc(dc, w, h, cx);
    }

    hidden function drawHr(dc, w, h, cx, fg) {
        var z = zones();
        var zi = (curHr != null && z.size() >= 6) ? zoneIndex(curHr, z) : null;
        var color = (zi != null) ? ZONE_COLORS[zi] : fg;
        var txt = (curHr != null) ? curHr.format("%d") : "--";
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.735, Graphics.FONT_MEDIUM,
            txt + ((zi != null) ? " Z" + (zi + 1).format("%d") : " bpm"),
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    // Bottom arc: the 5 HR zones as colored segments, needle at current HR.
    // Mirrors the pace gauge — 210deg (left) counter-clockwise to 330 (right).
    hidden function drawHrArc(dc, w, h, cx) {
        var z = zones();
        if (z == null || z.size() < 6) {
            return;
        }
        var lo = z[0].toFloat();
        var hi = z[5].toFloat();
        if (hi <= lo) {
            return;
        }
        var cy = h / 2;
        var r = (w / 2) - 8;
        // No needle down here — it collided with the next-step footer near
        // 6 o'clock. The ACTIVE zone renders thicker instead (and the big HR
        // number carries the zone color), which reads faster anyway.
        var zi = (curHr != null) ? zoneIndex(curHr, z) : -1;
        for (var i = 0; i < 5; i++) {
            var a1 = 210.0 + (z[i].toFloat() - lo) / (hi - lo) * 120.0;
            var a2 = 210.0 + (z[i + 1].toFloat() - lo) / (hi - lo) * 120.0;
            dc.setPenWidth(i == zi ? 21 : 11);
            dc.setColor(ZONE_COLORS[i], Graphics.COLOR_TRANSPARENT);
            dc.drawArc(cx, cy, r, Graphics.ARC_COUNTER_CLOCKWISE, a1, a2);
        }
        dc.setPenWidth(1);
    }

    // "2:14 left" -> "2:14" (the column label already says STEP LEFT)
    hidden function stripLeft(s) {
        var i = s.find(" left");
        return (i != null) ? s.substring(0, i) : s;
    }

    hidden function drawBasics(dc, w, h, cx, fg, dim) {
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.12, Graphics.FONT_SMALL, "PACE",
            Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.24, Graphics.FONT_NUMBER_HOT, paceStr(curSpeed),
            Graphics.TEXT_JUSTIFY_CENTER);

        var hrTxt = (curHr != null) ? curHr.format("%d") + " bpm" : "-- bpm";
        dc.drawText(cx, h * 0.56, Graphics.FONT_MEDIUM, hrTxt,
            Graphics.TEXT_JUSTIFY_CENTER);

        var dTxt = (dist != null) ? fmtDist(dist) : "0 m";
        dc.drawText(cx, h * 0.70, Graphics.FONT_MEDIUM, dTxt,
            Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        var cad = (curCad != null) ? curCad.format("%d") : "---";
        dc.drawText(cx, h * 0.82, Graphics.FONT_TINY,
            cad + " spm   " + strideStr() + " m",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    // truncate with ".." to fit maxW pixels
    hidden function fitText(dc, s, font, maxW) {
        if (s == null) {
            return "";
        }
        if (dc.getTextWidthInPixels(s, font) <= maxW) {
            return s;
        }
        var n = s.length();
        while (n > 1
            && dc.getTextWidthInPixels(s.substring(0, n) + "..", font) > maxW) {
            n--;
        }
        return s.substring(0, n) + "..";
    }
}
