using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Activity;
using Toybox.Lang;

// PaceForge Coach Field — full-screen (single-field layout) run data field.
// With an active structured workout: step name + notes, target pace band,
// live pace colored by drift vs the band, time/distance remaining in the
// step, and a next-step preview. Without a workout: pace / HR / distance.
class PaceForgeFieldView extends WatchUi.DataField {

    // live values, refreshed each compute()
    hidden var curSpeed = null;   // m/s or null
    hidden var curHr = null;
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

    function initialize() {
        DataField.initialize();
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
    }

    hidden function resetStepStart() {
        stepStartSec = timerSec;
        var info = Activity.getActivityInfo();
        if (info != null && info.elapsedDistance != null) {
            stepStartDist = info.elapsedDistance;
        } else {
            stepStartDist = 0.0;
        }
    }

    // ---- compute (1 Hz) ------------------------------------------------

    function compute(info) {
        curSpeed = (info != null) ? info.currentSpeed : null;
        curHr = (info != null) ? info.currentHeartRate : null;
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

        return null;
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

    function onUpdate(dc) {
        var bg = getBackgroundColor();
        var isDark = (bg == Graphics.COLOR_BLACK);
        var fg = isDark ? Graphics.COLOR_WHITE : Graphics.COLOR_BLACK;
        var dim = isDark ? Graphics.COLOR_LT_GRAY : Graphics.COLOR_DK_GRAY;

        dc.setColor(fg, bg);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        if (haveWorkout) {
            drawWorkout(dc, w, h, cx, fg, dim, isDark);
        } else {
            drawBasics(dc, w, h, cx, fg, dim);
        }
    }

    hidden function drawWorkout(dc, w, h, cx, fg, dim, isDark) {
        // step name (top)
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.08, Graphics.FONT_SMALL,
            fitText(dc, stepName, Graphics.FONT_SMALL, w * 0.72),
            Graphics.TEXT_JUSTIFY_CENTER);

        // notes (optional, one truncated line)
        if (stepNotes != null) {
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.185, Graphics.FONT_XTINY,
                fitText(dc, stepNotes, Graphics.FONT_XTINY, w * 0.84),
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        // big current pace, colored by drift vs band
        dc.setColor(driftColor(isDark, fg), Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.26, Graphics.FONT_NUMBER_HOT, paceStr(curSpeed),
            Graphics.TEXT_JUSTIFY_CENTER);

        // target band
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        var band;
        if (lowSpeed != null && highSpeed != null) {
            band = paceStr(highSpeed) + " - " + paceStr(lowSpeed) + " /km";
        } else {
            band = "no pace target";
        }
        dc.drawText(cx, h * 0.565, Graphics.FONT_SMALL, band,
            Graphics.TEXT_JUSTIFY_CENTER);

        // remaining in step
        if (!remainText.equals("")) {
            dc.drawText(cx, h * 0.675, Graphics.FONT_MEDIUM, remainText,
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        // next-step footer
        if (nextText != null) {
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.83, Graphics.FONT_XTINY,
                fitText(dc, nextText, Graphics.FONT_XTINY, w * 0.72),
                Graphics.TEXT_JUSTIFY_CENTER);
        }
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
    }

    // green inside band, amber within 5% outside, red beyond; neutral when
    // no band or standing still
    hidden function driftColor(isDark, fg) {
        if (curSpeed == null || curSpeed < 0.3
            || lowSpeed == null || highSpeed == null) {
            return fg;
        }
        if (curSpeed >= lowSpeed && curSpeed <= highSpeed) {
            return isDark ? Graphics.COLOR_GREEN : Graphics.COLOR_DK_GREEN;
        }
        if (curSpeed >= lowSpeed * 0.95 && curSpeed <= highSpeed * 1.05) {
            return Graphics.COLOR_ORANGE;
        }
        return Graphics.COLOR_RED;
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
