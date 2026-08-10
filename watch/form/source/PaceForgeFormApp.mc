using Toybox.Application;

class PaceForgeFormApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        return [new PaceForgeFormView()];
    }
}
