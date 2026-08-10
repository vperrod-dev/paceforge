using Toybox.Application;

class PaceForgeRaceApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        return [new PaceForgeRaceView()];
    }
}
