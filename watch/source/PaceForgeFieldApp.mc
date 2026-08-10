using Toybox.Application;

class PaceForgeFieldApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        return [new PaceForgeFieldView()];
    }
}
