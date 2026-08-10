using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Activity;
using Toybox.Lang;
using Toybox.Communications;
using Toybox.Application;

// PaceForge Race Field — half-marathon race day + ghost runs, full-screen
// (single 1-field data screen). Huge live PROJECTED FINISH extrapolated from
// avg pace so far, delta vs the goal time, current pace vs target pace with a
// verdict color, avg pace + HR footer. Race targets (distance, goal, target
// pace, prognosis) come from the PaceForge runner (data/watch-race.json) via
// the phone at startup and are cached; offline the field runs on the cached
// or baked values (HM distance, no goal -> big avg pace instead).
class PaceForgeRaceView extends WatchUi.DataField {

    hidden var curSpeed = null;   // m/s
    hidden var curHr = null;
    hidden var distM = null;      // elapsed meters
    hidden var timerSec = 0;

    // race targets — baked fallback: HM distance, no goal/target/prognosis
    hidden var raceKm = 21.0975;
    hidden var goalSec = null;        // goal finish time, seconds
    hidden var targetPaceSec = null;  // target pace, sec/km
    hidden var progSec = null;        // coach prognosis finish time, seconds

    hidden var TEAL = 0x00AA88;
    hidden var RED = 0xFF5544;
    hidden var AMBER = 0xFF8800;

    function initialize() {
        DataField.initialize();
        var v = Application.Storage.getValue("race_km");
        if (v != null) { raceKm = v.toFloat(); }
        v = Application.Storage.getValue("race_goal");
        if (v != null) { goalSec = v.toNumber(); }
        v = Application.Storage.getValue("race_tp");
        if (v != null) { targetPaceSec = v.toNumber(); }
        v = Application.Storage.getValue("race_prog");
        if (v != null) { progSec = v.toNumber(); }
        fetchRace();
    }

    // Pull race targets through the phone. Fire-and-forget: offline or no
    // phone -> cached/baked values, the run is unaffected.
    hidden function fetchRace() {
        if (!(Communications has :makeWebRequest) || RACE_URL.equals("")) {
            return;
        }
        try {
            Communications.makeWebRequest(RACE_URL, null,
                { :method => Communications.HTTP_REQUEST_METHOD_GET,
                  :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON },
                method(:onRace));
        } catch (e) {
        }
    }

    function onRace(code, data) {
        if (code != 200 || !(data instanceof Lang.Dictionary)) {
            return;
        }
        if (data["distance_km"] != null) {
            raceKm = data["distance_km"].toFloat();
            Application.Storage.setValue("race_km", raceKm);
        }
        // goal/target/prognosis are cleared when the server stops sending them
        goalSec = storeOrClear("race_goal", data["goal_time_sec"]);
        targetPaceSec = storeOrClear("race_tp", data["target_pace_sec_km"]);
        progSec = storeOrClear("race_prog", data["prognosis_time_sec"]);
    }

    hidden function storeOrClear(key, v) {
        if (v == null) {
            Application.Storage.deleteValue(key);
            return null;
        }
        var n = v.toNumber();
        Application.Storage.setValue(key, n);
        return n;
    }

    function compute(info) {
        curSpeed = (info != null) ? info.currentSpeed : null;
        curHr = (info != null) ? info.currentHeartRate : null;
        distM = (info != null) ? info.elapsedDistance : null;
        var tt = (info != null) ? info.timerTime : null;
        if (tt != null) {
            timerSec = tt / 1000;
        }
        return null;
    }

    // ---- projections ------------------------------------------------------

    // Linear extrapolation of the finish time from avg pace so far; needs at
    // least 0.5 km done so the projection isn't GPS-start noise.
    hidden function projectedSec() {
        if (distM == null || distM < 500.0 || timerSec <= 0) {
            return null;
        }
        return (timerSec.toFloat() / distM.toFloat() * raceKm * 1000.0).toNumber();
    }

    hidden function avgSpeed() {   // m/s or null
        if (distM == null || distM <= 0.0 || timerSec <= 0) {
            return null;
        }
        return distM.toFloat() / timerSec.toFloat();
    }

    // ---- drawing ----------------------------------------------------------

    function onUpdate(dc) {
        // white face — daylight legibility on MIP, same look as the Coach Field
        var bg = Graphics.COLOR_WHITE;
        var fg = Graphics.COLOR_BLACK;
        var dim = Graphics.COLOR_DK_GRAY;

        dc.setColor(fg, bg);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        // top: elapsed + km done
        var km = (distM != null) ? (distM / 1000.0).format("%.1f") : "0.0";
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.095, Graphics.FONT_SMALL,
            fmtTime(timerSec) + " · " + km + " km",
            Graphics.TEXT_JUSTIFY_CENTER);

        var proj = projectedSec();
        if (goalSec != null) {
            drawProjection(dc, w, h, cx, fg, dim, proj);
        } else {
            // no goal set -> the big number is the avg pace instead
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.185, Graphics.FONT_XTINY, "AVG PACE",
                Graphics.TEXT_JUSTIFY_CENTER);
            dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.225, Graphics.FONT_NUMBER_HOT, paceStr(avgSpeed()),
                Graphics.TEXT_JUSTIFY_CENTER);
            if (proj != null) {
                dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
                dc.drawText(cx, h * 0.53, Graphics.FONT_TINY,
                    "proj " + fmtTime(proj), Graphics.TEXT_JUSTIFY_CENTER);
            }
        }

        drawPaceLine(dc, w, h, cx, fg, dim);

        // bottom: avg pace + HR
        var hrTxt = (curHr != null) ? curHr.format("%d") : "--";
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.775, Graphics.FONT_SMALL,
            paceStr(avgSpeed()) + " avg   " + hrTxt + " bpm",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    hidden function drawProjection(dc, w, h, cx, fg, dim, proj) {
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.185, Graphics.FONT_XTINY, "PROJ FINISH",
            Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.225, Graphics.FONT_NUMBER_HOT,
            (proj != null) ? fmtTime(proj) : "--:--",
            Graphics.TEXT_JUSTIFY_CENTER);

        if (proj != null) {
            // delta vs the goal: teal when at/ahead of it, red when behind
            var d = proj - goalSec;
            var ahead = (d <= 0);
            dc.setColor(ahead ? TEAL : RED, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.475, Graphics.FONT_MEDIUM,
                (ahead ? "-" : "+") + fmtTime(ahead ? -d : d),
                Graphics.TEXT_JUSTIFY_CENTER);
        } else if (progSec != null) {
            // before 0.5 km the delta slot shows the coach's prognosis
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.495, Graphics.FONT_TINY,
                "prog " + fmtTime(progSec), Graphics.TEXT_JUSTIFY_CENTER);
        }
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.585, Graphics.FONT_XTINY,
            "vs " + fmtTime(goalSec) + " goal",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    // current pace vs target pace, colored by how far off target we are:
    // teal within 3%, amber within 6%, red beyond
    hidden function drawPaceLine(dc, w, h, cx, fg, dim) {
        var y = h * 0.655;
        if (targetPaceSec == null) {
            dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, y, Graphics.FONT_SMALL, paceStr(curSpeed) + " /km",
                Graphics.TEXT_JUSTIFY_CENTER);
            return;
        }
        var color = fg;
        if (curSpeed != null && curSpeed >= 0.3) {
            var cur = 1000.0 / curSpeed;                       // sec/km
            var off = (cur - targetPaceSec).abs() / targetPaceSec;
            color = (off <= 0.03) ? TEAL : ((off <= 0.06) ? AMBER : RED);
        }
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, y, Graphics.FONT_SMALL,
            paceStr(curSpeed) + " vs " + fmtPaceSec(targetPaceSec) + " /km",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    // ---- formatting -------------------------------------------------------

    hidden function paceStr(speed) {
        if (speed == null || speed < 0.3) {
            return "--:--";
        }
        return fmtPaceSec((1000.0 / speed).toNumber());
    }

    hidden function fmtPaceSec(secPerKm) {
        var s = secPerKm.toNumber();
        if (s > 5999) {   // cap at 99:59
            s = 5999;
        }
        return (s / 60).format("%d") + ":" + (s % 60).format("%02d");
    }

    hidden function fmtTime(sec) {
        var s = sec.toNumber();
        if (s >= 3600) {
            return (s / 3600).format("%d") + ":" + ((s % 3600) / 60).format("%02d")
                + ":" + (s % 60).format("%02d");
        }
        return (s / 60).format("%d") + ":" + (s % 60).format("%02d");
    }
}
