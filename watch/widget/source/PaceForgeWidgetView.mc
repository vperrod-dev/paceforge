using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Communications;
using Toybox.Application;
using Toybox.Lang;

// PaceForge Coach widget — glance + full view of today's session and the
// coach's morning headline, fetched from the runner through the phone and
// cached so it still shows the last brief offline.

(:glance)
class PaceForgeGlanceView extends WatchUi.GlanceView {

    function initialize() {
        GlanceView.initialize();
    }

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, dc.getHeight() / 4, Graphics.FONT_GLANCE, "PaceForge",
            Graphics.TEXT_JUSTIFY_LEFT);
        var s = Application.Storage.getValue("wb_session");
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, dc.getHeight() * 5 / 8, Graphics.FONT_GLANCE,
            (s != null && !s.equals("")) ? s : "Today's session",
            Graphics.TEXT_JUSTIFY_LEFT);
    }
}

class PaceForgeWidgetView extends WatchUi.View {

    hidden var headline = null;
    hidden var session = null;
    hidden var detail = null;
    hidden var status = "loading...";

    function initialize() {
        View.initialize();
        session = Application.Storage.getValue("wb_session");
        headline = Application.Storage.getValue("wb_headline");
        detail = Application.Storage.getValue("wb_detail");
    }

    function onShow() {
        fetchBrief();
    }

    hidden function fetchBrief() {
        if (!(Communications has :makeWebRequest) || BRIEF_URL.equals("")) {
            status = "no comms";
            return;
        }
        try {
            Communications.makeWebRequest(BRIEF_URL, null,
                { :method => Communications.HTTP_REQUEST_METHOD_GET,
                  :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON },
                method(:onBrief));
        } catch (e) {
            status = "offline";
        }
    }

    function onBrief(code, data) {
        if (code == 200 && data instanceof Lang.Dictionary) {
            session = data["session"];
            headline = data["headline"];
            detail = data["detail"];
            status = "";
            Application.Storage.setValue("wb_session", session);
            Application.Storage.setValue("wb_headline", headline);
            Application.Storage.setValue("wb_detail", detail);
        } else {
            status = (session != null) ? "cached" : ("error " + code);
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.10, Graphics.FONT_TINY, "TODAY'S SESSION",
            Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        var name = (session != null && !session.equals("")) ? session : "Rest / nothing planned";
        dc.drawText(cx, h * 0.18, Graphics.FONT_MEDIUM,
            fit(dc, name, Graphics.FONT_MEDIUM, w * 0.86), Graphics.TEXT_JUSTIFY_CENTER);

        if (detail != null && !detail.equals("")) {
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.30, Graphics.FONT_SMALL, detail,
                Graphics.TEXT_JUSTIFY_CENTER);
        }

        // headline, wrapped to ~3 lines
        if (headline != null && !headline.equals("")) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            var lines = wrap(dc, headline, Graphics.FONT_TINY, w * 0.82);
            var y = h * 0.44;
            for (var i = 0; i < lines.size() && i < 4; i++) {
                dc.drawText(cx, y, Graphics.FONT_TINY, lines[i], Graphics.TEXT_JUSTIFY_CENTER);
                y += h * 0.085;
            }
        }

        if (!status.equals("")) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.86, Graphics.FONT_XTINY, status,
                Graphics.TEXT_JUSTIFY_CENTER);
        }
    }

    hidden function fit(dc, s, font, maxW) {
        if (dc.getTextWidthInPixels(s, font) <= maxW) {
            return s;
        }
        var n = s.length();
        while (n > 1 && dc.getTextWidthInPixels(s.substring(0, n) + "..", font) > maxW) {
            n--;
        }
        return s.substring(0, n) + "..";
    }

    hidden function wrap(dc, s, font, maxW) {
        var words = splitWords(s);
        var lines = [];
        var cur = "";
        for (var i = 0; i < words.size(); i++) {
            var cand = cur.equals("") ? words[i] : cur + " " + words[i];
            if (dc.getTextWidthInPixels(cand, font) <= maxW) {
                cur = cand;
            } else {
                if (!cur.equals("")) {
                    lines.add(cur);
                }
                cur = words[i];
            }
        }
        if (!cur.equals("")) {
            lines.add(cur);
        }
        return lines;
    }

    hidden function splitWords(s) {
        var out = [];
        var start = 0;
        for (var i = 0; i <= s.length(); i++) {
            if (i == s.length() || s.substring(i, i + 1).equals(" ")) {
                if (i > start) {
                    out.add(s.substring(start, i));
                }
                start = i + 1;
            }
        }
        return out;
    }
}
