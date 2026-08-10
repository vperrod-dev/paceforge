using Toybox.Application;
using Toybox.WatchUi;

(:glance)
class PaceForgeWidgetApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        return [new PaceForgeWidgetView()];
    }

    function getGlanceView() {
        return [new PaceForgeGlanceView()];
    }
}
