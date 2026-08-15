"""Provide lightweight stubs for optional Garmin packages so the test suite can
import PaceForge without the real third-party dependency being installed.

Only stub when the real package is missing — stubbing unconditionally shadows
an installed garminconnect with attribute-less placeholder classes and breaks
every test that exercises workout-step conversion (seen 2026-07-31: 34 tests
failing with `ConditionType has no attribute 'DISTANCE'`).
"""

import importlib.util
import sys
import types

import pytest

from paceforge import store

# Real values mirrored from garminconnect.workout so the stub path exercises
# the same constants the client code uses.
_STEP_TYPE = {"WARMUP": 1, "COOLDOWN": 2, "INTERVAL": 3, "RECOVERY": 4, "REST": 5, "REPEAT": 6}
_CONDITION_TYPE = {"DISTANCE": 1, "TIME": 2, "HEART_RATE": 3, "CALORIES": 4, "CADENCE": 5, "POWER": 6}
_TARGET_TYPE = {"NO_TARGET": 1, "POWER": 2, "CADENCE": 3, "HEART_RATE": 4, "SPEED": 5, "OPEN": 6}


@pytest.fixture(autouse=True)
def _no_garmin_write_pacing(monkeypatch):
    """Drop the real Garmin throttles — tests would otherwise sleep through them."""
    from paceforge.garmin import client as garmin_client
    monkeypatch.setattr(garmin_client, "WRITE_PACE_SECONDS", 0)
    monkeypatch.setattr(garmin_client, "READ_PACE_SECONDS", 0)


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Hard-block every test from touching the live checkout's data/ dir.

    store.DATA_DIR is bound at import time from PACEFORGE_DATA_DIR, so setting
    the env var alone does nothing for already-imported code — a test (or a
    test written later) that forgets to mock store.load_plan/save_plan would
    otherwise read/write Victor's real plan.json. This happened repeatedly
    (2026-07-29, -30, -31): the live plan got silently replaced by a test's
    dummy "Test Plan" scaffold. Redirecting the module-level constant itself
    makes that class of bug impossible regardless of per-test mocking discipline.
    """
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def pytest_configure(config):  # noqa: ARG001
    if importlib.util.find_spec("garminconnect") is not None:
        return  # real dependency installed — never shadow it
    garmin = types.ModuleType("garminconnect")
    garmin.Garmin = type("Garmin", (), {})
    sys.modules["garminconnect"] = garmin

    workout = types.ModuleType("garminconnect.workout")
    for _name in ["ExecutableStep", "RunningWorkout", "WorkoutSegment", "create_repeat_group"]:
        setattr(workout, _name, type(_name, (), {}))
    for _name, _members in [("StepType", _STEP_TYPE), ("ConditionType", _CONDITION_TYPE),
                            ("TargetType", _TARGET_TYPE)]:
        setattr(workout, _name, type(_name, (), _members))
    sys.modules["garminconnect.workout"] = workout
    garmin.workout = workout

    aio = types.ModuleType("garminconnect_aio")
    sys.modules["garminconnect_aio"] = aio
