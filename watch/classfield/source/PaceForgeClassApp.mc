using Toybox.Application;

class PaceForgeClassApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        return [new PaceForgeClassView()];
    }
}
