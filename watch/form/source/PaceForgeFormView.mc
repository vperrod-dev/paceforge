using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Activity;
using Toybox.Math;
using Toybox.Lang;
using Toybox.Communications;
using Toybox.Application;

// PaceForge Form Field — companion data screen to the Coach Field, focused on
// the form numbers being worked on: BIG cadence with a target-band arc gauge,
// BIG stride length, small pace + HR footer. Add it as a second 1-field data
// screen and swipe between the two mid-run.
class PaceForgeFormView extends WatchUi.DataField {

    hidden var curSpeed = null;   // m/s
    hidden var curHr = null;
    hidden var curCad = null;     // steps/min

    // Cadence target band shown teal on the gauge — the COACH's current
    // prescription, fetched from the PaceForge runner (data/watch-targets.json)
    // via the phone at startup and cached; baked default = the prescription at
    // build time. Gauge domain is 140-200.
    hidden var CAD_LO = 168.0;
    hidden var CAD_HI = 172.0;
    hidden var DOM_LO = 140.0;
    hidden var DOM_HI = 200.0;

    hidden var TEAL = 0x00AA88;
    hidden var RED = 0xFF5544;
    hidden var AMBER = 0xFF8800;
    hidden var GREY = 0x555555;

    function initialize() {
        DataField.initialize();
        // last coach targets we saw (survives across activities)
        var lo = Application.Storage.getValue("cad_lo");
        var hi = Application.Storage.getValue("cad_hi");
        if (lo != null && hi != null) {
            CAD_LO = lo.toFloat();
            CAD_HI = hi.toFloat();
        }
        fetchTargets();
    }

    // Pull the coach's current cadence band through the phone. Fire-and-forget:
    // offline or no phone -> keep cached/baked values, the workout is unaffected.
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
            && data["cadence_lo"] != null && data["cadence_hi"] != null) {
            CAD_LO = data["cadence_lo"].toFloat();
            CAD_HI = data["cadence_hi"].toFloat();
            Application.Storage.setValue("cad_lo", CAD_LO);
            Application.Storage.setValue("cad_hi", CAD_HI);
        }
    }

    function compute(info) {
        curSpeed = (info != null) ? info.currentSpeed : null;
        curHr = (info != null) ? info.currentHeartRate : null;
        curCad = null;
        if (info != null && info.currentCadence != null && info.currentCadence > 0) {
            var c = info.currentCadence.toNumber();
            // strides/min firmwares report ~85; nobody runs at <120 steps/min
            curCad = (c < 120) ? c * 2 : c;
        }
        return null;
    }

    // ---- drawing ----------------------------------------------------------

    function onUpdate(dc) {
        var bg = Graphics.COLOR_WHITE;
        var fg = Graphics.COLOR_BLACK;
        var dim = Graphics.COLOR_DK_GRAY;

        dc.setColor(fg, bg);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        drawCadArc(dc, w, h, cx);

        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.135, Graphics.FONT_SMALL, "CADENCE", Graphics.TEXT_JUSTIFY_CENTER);

        // big cadence, colored vs the target band
        dc.setColor(cadColor(fg), Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.20, Graphics.FONT_NUMBER_HOT,
            (curCad != null) ? curCad.format("%d") : "---",
            Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.455, Graphics.FONT_TINY, "steps / min",
            Graphics.TEXT_JUSTIFY_CENTER);

        // big stride
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.545, Graphics.FONT_NUMBER_MILD, strideStr(),
            Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(dim, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.70, Graphics.FONT_TINY, "stride m",
            Graphics.TEXT_JUSTIFY_CENTER);

        // pace + HR footer
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        var hrTxt = (curHr != null) ? curHr.format("%d") : "--";
        dc.drawText(cx, h * 0.79, Graphics.FONT_SMALL,
            paceStr(curSpeed) + " /km   " + hrTxt + " bpm",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    hidden function cadColor(fg) {
        if (curCad == null) {
            return fg;
        }
        if (curCad >= CAD_LO && curCad <= CAD_HI) {
            return TEAL;
        }
        if (curCad >= CAD_LO - 8 && curCad <= CAD_HI + 8) {
            return AMBER;
        }
        return RED;
    }

    // Top arc gauge: teal target band inside a 140-200 spm domain, needle at
    // the current cadence. Same geometry as the Coach Field's pace gauge.
    hidden function drawCadArc(dc, w, h, cx) {
        var cy = h / 2;
        var r = (w / 2) - 8;
        var f1 = (CAD_LO - DOM_LO) / (DOM_HI - DOM_LO);
        var f2 = (CAD_HI - DOM_LO) / (DOM_HI - DOM_LO);
        dc.setPenWidth(13);
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(0.0), fracDeg(f1));
        dc.setColor(TEAL, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(f1), fracDeg(f2));
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, fracDeg(f2), fracDeg(1.0));
        dc.setPenWidth(1);

        if (curCad != null) {
            var f = (curCad.toFloat() - DOM_LO) / (DOM_HI - DOM_LO);
            if (f < 0.0) { f = 0.0; }
            if (f > 1.0) { f = 1.0; }
            var a = fracDeg(f) * Math.PI / 180.0;
            var tip = [cx + (r - 14.0) * Math.cos(a), cy - (r - 14.0) * Math.sin(a)];
            var b1 = [cx + (r - 26.0) * Math.cos(a - 4.0 * Math.PI / 180.0),
                      cy - (r - 26.0) * Math.sin(a - 4.0 * Math.PI / 180.0)];
            var b2 = [cx + (r - 26.0) * Math.cos(a + 4.0 * Math.PI / 180.0),
                      cy - (r - 26.0) * Math.sin(a + 4.0 * Math.PI / 180.0)];
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            dc.fillPolygon([tip, b1, b2]);
        }
    }

    hidden function fracDeg(f) {
        return 150.0 - f * 120.0;   // low on the left, high on the right
    }

    hidden function strideStr() {
        if (curSpeed == null || curSpeed < 0.3 || curCad == null || curCad < 60) {
            return "-.--";
        }
        return (curSpeed * 60.0 / curCad).format("%.2f");
    }

    hidden function paceStr(speed) {
        if (speed == null || speed < 0.3) {
            return "--:--";
        }
        var secPerKm = (1000.0 / speed).toNumber();
        if (secPerKm > 5999) {
            secPerKm = 5999;
        }
        return (secPerKm / 60).format("%d") + ":" + (secPerKm % 60).format("%02d");
    }
}
