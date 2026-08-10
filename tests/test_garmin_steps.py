"""Tests for Garmin workout step conversion with pace targets."""

from paceforge.engine.vdot import paces_from_vdot
from paceforge.engine.workouts import WorkoutFactory
from paceforge.garmin.client import (
    _build_garmin_description,
    _fallback_steps,
    _renumber_steps,
    _to_garmin_step,
)
from paceforge.models.plan import (
    IntensityTarget,
    Workout,
    WorkoutStep,
    WorkoutStepType,
    WorkoutType,
)


class TestGarminStepConversion:
    def test_warmup_step_time_based(self):
        step = WorkoutStep(step_type=WorkoutStepType.WARMUP, duration_seconds=600)
        result = _to_garmin_step(step)
        assert result.stepType["stepTypeKey"] == "warmup"
        assert result.endCondition["conditionTypeKey"] == "time"
        assert result.endConditionValue == 600

    def test_interval_with_pace_target(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.INTERVAL,
            duration_seconds=210,
            target_type=IntensityTarget.PACE,
            target_low=240.0,   # 4:00/km
            target_high=250.0,  # 4:10/km
        )
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeId"] == 6  # pace.zone
        assert result.targetType["workoutTargetTypeKey"] == "pace.zone"
        # 1000/250 = 4.0 m/s (faster pace = higher speed)
        # 1000/240 ≈ 4.1667 m/s
        assert hasattr(result, "targetValueOne")
        assert hasattr(result, "targetValueTwo")
        assert result.targetValueOne < result.targetValueTwo

    def test_single_pace_widened_to_nonzero_range(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            duration_seconds=1800,
            target_type=IntensityTarget.PACE,
            target_low=290.0,   # easy step written with one pace on both bounds
            target_high=290.0,
        )
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeId"] == 6  # pace.zone
        assert result.targetValueOne < result.targetValueTwo  # not a zero-width no-op

    def test_distance_based_step(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            distance_meters=5000,
            target_low=330.0,
            target_high=350.0,
        )
        result = _to_garmin_step(step)
        assert result.endCondition["conditionTypeId"] == 1  # DISTANCE
        assert result.endConditionValue == 5000

    def test_repeat_group(self):
        sub1 = WorkoutStep(
            step_type=WorkoutStepType.INTERVAL,
            duration_seconds=210,
            target_low=240.0,
            target_high=250.0,
        )
        sub2 = WorkoutStep(
            step_type=WorkoutStepType.RECOVERY,
            duration_seconds=120,
        )
        group = WorkoutStep(
            step_type=WorkoutStepType.INTERVAL,
            repeat_count=5,
            steps=[sub1, sub2],
        )
        result = _to_garmin_step(group)
        assert result.numberOfIterations == 5
        assert len(result.workoutSteps) == 2

    def test_no_target_when_no_pace(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            duration_seconds=1800,
        )
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeId"] == 1  # NO_TARGET

    def test_step_order_passed(self):
        step = WorkoutStep(step_type=WorkoutStepType.COOLDOWN, duration_seconds=600)
        result = _to_garmin_step(step, order=3)
        assert result.stepOrder == 3

    def test_active_step_maps_to_interval(self):
        step = WorkoutStep(step_type=WorkoutStepType.ACTIVE, duration_seconds=600)
        result = _to_garmin_step(step)
        assert result.stepType == {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}

    def test_rest_step_maps_to_rest(self):
        step = WorkoutStep(step_type=WorkoutStepType.REST, duration_seconds=60)
        result = _to_garmin_step(step)
        assert result.stepType == {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}

    def test_zero_width_pace_uses_plan_band_when_available(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            duration_seconds=1800,
            target_type=IntensityTarget.PACE,
            target_low=290.0,
            target_high=290.0,
            pace_key="easy",
        )
        result = _to_garmin_step(step, pace_bands={"easy": [285.0, 320.0]})
        assert result.targetValueOne == round(1000.0 / 320.0, 4)  # slow edge of the band
        assert result.targetValueTwo == round(1000.0 / 285.0, 4)  # fast edge of the band

    def test_zero_width_pace_falls_back_to_plus_minus_3(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            duration_seconds=1800,
            target_type=IntensityTarget.PACE,
            target_low=290.0,
            target_high=290.0,
            pace_key="easy",
        )
        result = _to_garmin_step(step)  # no pace_bands
        assert result.targetValueOne == round(1000.0 / 293.0, 4)
        assert result.targetValueTwo == round(1000.0 / 287.0, 4)

    def test_step_description_propagated(self):
        step = WorkoutStep(step_type=WorkoutStepType.ACTIVE, duration_seconds=600,
                           description="Relaxed, conversational effort")
        result = _to_garmin_step(step)
        assert result.description == "Relaxed, conversational effort"

    def test_step_description_truncated_to_200(self):
        step = WorkoutStep(step_type=WorkoutStepType.ACTIVE, duration_seconds=600,
                           description="x" * 300)
        result = _to_garmin_step(step)
        assert len(result.description) == 200

    def test_heart_rate_step_emits_custom_bpm_range(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            duration_seconds=1800,
            target_type=IntensityTarget.HEART_RATE,
            target_low=140.0,
            target_high=155.0,
        )
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeId"] == 4
        assert result.targetType["workoutTargetTypeKey"] == "heart.rate.zone"
        assert result.targetValueOne == 140.0
        assert result.targetValueTwo == 155.0


class TestSportInference:
    def test_hyrox_and_station_workouts_push_as_fitness_equipment(self):
        from paceforge.garmin.client import _sport_for

        brick = Workout(name="Brick", workout_type=WorkoutType.HYROX_MIXED)
        stations = Workout(name="Stations", workout_type=WorkoutType.CROSS_TRAINING)
        run = Workout(name="Easy", workout_type=WorkoutType.EASY_RUN)
        assert _sport_for(brick)["sportTypeKey"] == "fitness_equipment"
        assert _sport_for(stations)["sportTypeKey"] == "fitness_equipment"
        assert _sport_for(run)["sportTypeKey"] == "running"


def test_stepless_workout_gets_a_fallback_paced_step():
    wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy shakeout",
                 estimated_distance_meters=5000)
    steps = _fallback_steps(wo, {"easy_pace": 300.0})
    assert len(steps) == 1
    assert steps[0].distance_meters == 5000
    assert steps[0].target_low and steps[0].target_high  # paced, so Garmin guides it


class TestRecoveryRestTargets:
    def test_recovery_step_with_pace_band_has_no_target(self):
        step = WorkoutStep(step_type=WorkoutStepType.RECOVERY, duration_seconds=120,
                           target_type=IntensityTarget.PACE,
                           target_low=290.0, target_high=320.0)
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeKey"] == "no.target"

    def test_rest_step_with_pace_band_has_no_target(self):
        step = WorkoutStep(step_type=WorkoutStepType.REST, duration_seconds=60,
                           target_type=IntensityTarget.PACE,
                           target_low=290.0, target_high=320.0)
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeKey"] == "no.target"

    def test_warmup_keeps_its_pace_band(self):
        step = WorkoutStep(step_type=WorkoutStepType.WARMUP, duration_seconds=600,
                           target_type=IntensityTarget.PACE,
                           target_low=290.0, target_high=320.0)
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeKey"] == "pace.zone"


def _repeat_group_step() -> WorkoutStep:
    return WorkoutStep(
        step_type=WorkoutStepType.INTERVAL,
        description="4 x 3min VO2max",
        repeat_count=4,
        steps=[
            WorkoutStep(step_type=WorkoutStepType.INTERVAL, duration_seconds=180,
                        target_low=240.0, target_high=250.0),
            WorkoutStep(step_type=WorkoutStepType.RECOVERY, duration_seconds=90),
        ],
    )


def test_repeat_group_carries_description():
    result = _to_garmin_step(_repeat_group_step())
    assert result.description == "4 x 3min VO2max"


def test_tree_renumbered_globally_with_child_step_ids():
    steps = [
        _to_garmin_step(WorkoutStep(step_type=WorkoutStepType.WARMUP,
                                    duration_seconds=600), order=1),
        _to_garmin_step(_repeat_group_step(), order=2),
        _to_garmin_step(WorkoutStep(step_type=WorkoutStepType.COOLDOWN,
                                    duration_seconds=600), order=3),
    ]
    _renumber_steps(steps)
    group = steps[1]
    assert [steps[0].stepOrder, group.stepOrder, steps[2].stepOrder] == [1, 2, 5]
    assert [c.stepOrder for c in group.workoutSteps] == [3, 4]
    assert [c.childStepId for c in group.workoutSteps] == [1, 1]
    assert steps[0].childStepId is None  # top-level steps stay untagged


class TestFallbackSteps:
    def test_cross_training_gets_timed_step_with_no_pace_target(self):
        wo = Workout(workout_type=WorkoutType.CROSS_TRAINING, name="HIIT class",
                     estimated_duration_seconds=2700)
        steps = _fallback_steps(wo, {"easy_pace": 300.0}, {"easy": [285.0, 320.0]})
        assert steps[0].target_type == IntensityTarget.OPEN
        assert steps[0].target_low is None
        assert steps[0].duration_seconds == 2700

    def test_race_day_uses_race_band(self):
        wo = Workout(workout_type=WorkoutType.RACE_PACE, name="RACE DAY: Half",
                     estimated_distance_meters=21097)
        steps = _fallback_steps(wo, {"easy_pace": 300.0},
                                {"easy": [285.0, 320.0], "race": [255.0, 268.0]})
        assert (steps[0].target_low, steps[0].target_high) == (255.0, 268.0)

    def test_race_day_without_race_band_stays_open(self):
        wo = Workout(workout_type=WorkoutType.RACE_PACE, name="RACE DAY: Half",
                     estimated_distance_meters=21097)
        steps = _fallback_steps(wo, {"easy_pace": 300.0}, {"easy": [285.0, 320.0]})
        assert steps[0].target_type == IntensityTarget.OPEN

    def test_easy_run_uses_easy_band(self):
        wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy 8k",
                     estimated_distance_meters=8000)
        steps = _fallback_steps(wo, {"easy_pace": 300.0}, {"easy": [285.0, 320.0]})
        assert (steps[0].target_low, steps[0].target_high) == (285.0, 320.0)

    def test_modest_window_is_not_inverted(self):
        wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy 8k",
                     estimated_distance_meters=8000)
        steps = _fallback_steps(wo, {"easy_pace": 300.0})
        assert (steps[0].target_low, steps[0].target_high) == (295.0, 305.0)


def test_time_trial_step_is_open_with_prediction_in_description():
    factory = WorkoutFactory(paces_from_vdot(50.0))
    wo = factory.time_trial(5)
    tt = wo.steps[1]
    assert tt.target_type == IntensityTarget.OPEN
    assert tt.target_low is None
    assert "predicts ~" in tt.description


class TestGarminDescription:
    def test_leads_with_briefing_purpose_and_drops_pace_step_recaps(self):
        wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy 8k",
                     estimated_distance_meters=8000,
                     briefing={"purpose": "Aerobic maintenance between quality days.",
                               "feel": "Conversational"},
                     notes="Keep it honest.")
        desc = _build_garmin_description(wo, {"easy_pace": 300.0})
        assert desc.startswith("Aerobic maintenance")
        assert "Paces:" not in desc
        assert "Steps:" not in desc
        assert "Keep it honest." in desc

    def test_truncates_at_a_word_boundary(self):
        wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy 8k",
                     briefing={"purpose": "Sharpen."},
                     notes="wordishly " * 100)
        desc = _build_garmin_description(wo, None)
        assert len(desc) <= 500
        assert desc.endswith("…")
        assert desc[:-1].split()[-1] == "wordishly"  # never cut mid-word


def test_full_wire_payload_easy_strides():
    """Easy+strides through the real upload path — tree numbering + envelope."""
    from paceforge.garmin.client import _RUNNING_SPORT, GarminClient

    factory = WorkoutFactory(paces_from_vdot(50.0))
    wo = factory.easy_with_strides(8, 6)
    wo.briefing = {"purpose": "Leg speed on easy legs.",
                   "feel": "Fast but never straining",
                   "cue": "Tall hips, quick feet"}
    captured = {}

    class _FakeGarmin:
        def upload_running_workout(self, gw):  # noqa: ANN001
            captured["gw"] = gw
            return {"workoutId": 1}

    client = GarminClient(email="a@example.com", password="x", token_dir="")
    client._client = _FakeGarmin()
    client._upload(wo, _RUNNING_SPORT, {"easy_pace": 300.0},
                   pace_bands={"easy": [285.0, 320.0]})
    payload = captured["gw"].to_dict()

    assert payload["estimatedDistanceInMeters"] == 8000.0
    assert payload["description"].startswith("Leg speed on easy legs.")
    easy, group = payload["workoutSegments"][0]["workoutSteps"]
    assert (easy["stepOrder"], group["stepOrder"]) == (1, 2)
    assert "childStepId" not in easy
    stride, rest = group["workoutSteps"]
    assert (stride["stepOrder"], rest["stepOrder"]) == (3, 4)
    assert (stride["childStepId"], rest["childStepId"]) == (1, 1)
    assert group["numberOfIterations"] == 6
    assert group["description"] == "6 x strides"
    assert rest["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert rest["description"] == "45s walking rest"
    # Work steps carry the briefing feel instead of restating the target.
    assert stride["description"] == "Fast but never straining"
    assert easy["description"] == "Fast but never straining"
    assert stride["targetType"]["workoutTargetTypeKey"] == "pace.zone"
