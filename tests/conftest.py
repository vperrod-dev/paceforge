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

# Real values mirrored from garminconnect.workout so the stub path exercises
# the same constants the client code uses.
_STEP_TYPE = {"WARMUP": 1, "COOLDOWN": 2, "INTERVAL": 3, "RECOVERY": 4, "REST": 5, "REPEAT": 6}
_CONDITION_TYPE = {"DISTANCE": 1, "TIME": 2, "HEART_RATE": 3, "CALORIES": 4, "CADENCE": 5, "POWER": 6}
_TARGET_TYPE = {"NO_TARGET": 1, "POWER": 2, "CADENCE": 3, "HEART_RATE": 4, "SPEED": 5, "OPEN": 6}


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
