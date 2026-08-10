using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Activity;
using Toybox.Math;
using Toybox.Lang;
using Toybox.UserProfile;
using Toybox.Communications;
using Toybox.Application;

// PaceForge Class Field — for cardio/HYROX-style classes, where the session
// IS heart-rate management: full-circle zone ring (active zone thick), BIG
// zone-colored HR, live time-in-zone bars, elapsed time, and the coach's
// recovery ceiling (watch-targets.json "recover_to") when you're above it.
class PaceForgeClassView extends WatchUi.DataField {

    hidden var curHr = null;
    hidden var timerSec = 0;
    hidden var lastTimerSec = -1;
    hidden var zoneSecs = [0, 0, 0, 0, 0];   // accumulated seconds per zone
    hidden var recoverTo = null;             // coach ceiling, bpm (optional)

    hidden var ZONE_COLORS = [0x999999, 0x3B8AD8, 0x00AA55, 0xFF8800, 0xE0402F];
    hidden var GREY = 0x555555;
    hidden var hrZones = null;

    function initialize() {
        DataField.initialize();
        var r = Application.Storage.getValue("recover_to");
        if (r != null) {
            recoverTo = r.toNumber();
        }
        fetchTargets();
    }

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
        if (code == 200 && data instanceof Lang.Dictionary
            && data["recover_to"] != null) {
            recoverTo = data["recover_to"].toNumber();
            Application.Storage.setValue("recover_to", recoverTo);
        }
    }

    hidden function zones() {
        if (hrZones == null) {
            try {
                // Classes record under cardio/HIIT profiles; generic zones fit best.
                hrZones = UserProfile.getHeartRateZones(UserProfile.HR_ZONE_SPORT_GENERIC);
            } catch (e) {
                hrZones = [];
            }
        }
        return hrZones;
    }

    hidden function zoneIndex(hr, z) {
        for (var i = 5; i >= 2; i--) {
            if (hr > z[i - 1]) {
                return i - 1;
            }
        }
        return 0;
    }

    function compute(info) {
        curHr = (info != null) ? info.currentHeartRate : null;
        var tt = (info != null) ? info.timerTime : null;
        if (tt != null) {
            timerSec = tt / 1000;
        }
        // accumulate time-in-zone only while the timer advances (not paused)
        var z = zones();
        if (curHr != null && z != null && z.size() >= 6
            && lastTimerSec >= 0 && timerSec > lastTimerSec) {
            var zi = zoneIndex(curHr, z);
            zoneSecs[zi] = zoneSecs[zi] + (timerSec - lastTimerSec);
        }
        lastTimerSec = timerSec;
        return null;
    }

    function onTimerReset() {
        zoneSecs = [0, 0, 0, 0, 0];
        lastTimerSec = -1;
    }

    // ---- drawing ----------------------------------------------------------

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var fg = Graphics.COLOR_BLACK;
        var dim = Graphics.COLOR_DK_GRAY;

        drawZoneRing(dc, w, h, cx);

        // elapsed — big enough to read without squinting
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.095, Graphics.FONT_MEDIUM, fmtTime(timerSec),
            Graphics.TEXT_JUSTIFY_CENTER);

        // BIG heart rate, zone-colored
        var z = zones();
        var zi = (curHr != null && z != null && z.size() >= 6) ? zoneIndex(curHr, z) : null;
        dc.setColor((zi != null) ? ZONE_COLORS[zi] : fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.205, Graphics.FONT_NUMBER_HOT,
            (curHr != null) ? curHr.format("%d") : "--",
            Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx, h * 0.465, Graphics.FONT_TINY,
            (zi != null) ? "ZONE " + (zi + 1).format("%d") : "bpm",
            Graphics.TEXT_JUSTIFY_CENTER);

        drawZoneBars(dc, w, h, fg, dim);

        // coach's recovery ceiling — shown only when you're above it
        if (recoverTo != null && curHr != null && curHr > recoverTo) {
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.835, Graphics.FONT_XTINY,
                "RECOVER TO " + recoverTo.format("%d"),
                Graphics.TEXT_JUSTIFY_CENTER);
        }
    }

    // Full-circle zone ring: the 5 zones proportionally around the rim,
    // active zone thicker. Starts at 12 o'clock, clockwise.
    hidden function drawZoneRing(dc, w, h, cx) {
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
        var r = (w / 2) - 7;
        var zi = (curHr != null) ? zoneIndex(curHr, z) : -1;
        for (var i = 0; i < 5; i++) {
            var f1 = (z[i].toFloat() - lo) / (hi - lo);
            var f2 = (z[i + 1].toFloat() - lo) / (hi - lo);
            dc.setPenWidth(i == zi ? 19 : 9);
            dc.setColor(ZONE_COLORS[i], Graphics.COLOR_TRANSPARENT);
            // clockwise from 12 o'clock: degrees decrease from 90
            dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE,
                90 - (f1 * 360.0).toNumber(), 90 - (f2 * 360.0).toNumber());
        }
        dc.setPenWidth(1);
    }

    // Five horizontal time-in-zone bars, widths relative to the longest zone.
    hidden function drawZoneBars(dc, w, h, fg, dim) {
        var maxSec = 60;   // floor so early bars don't fill the row instantly
        for (var i = 0; i < 5; i++) {
            if (zoneSecs[i] > maxSec) {
                maxSec = zoneSecs[i];
            }
        }
        var x0 = w * 0.30;
        var maxW = w * 0.42;
        for (var i = 0; i < 5; i++) {
            var y = h * (0.545 + i * 0.055);
            dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w * 0.27, y - 2, Graphics.FONT_XTINY, "Z" + (i + 1).format("%d"),
                Graphics.TEXT_JUSTIFY_RIGHT);
            var bw = (maxW * zoneSecs[i] / maxSec).toNumber();
            dc.setColor(ZONE_COLORS[i], Graphics.COLOR_TRANSPARENT);
            if (bw > 0) {
                dc.fillRectangle(x0, y, bw, 9);
            }
            dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
            var mins = (zoneSecs[i] / 60).toNumber();
            dc.drawText(x0 + maxW + 6, y - 2, Graphics.FONT_XTINY,
                mins.format("%d") + "m", Graphics.TEXT_JUSTIFY_LEFT);
        }
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
