"""Tests for Garmin workout step conversion with pace targets."""

from paceforge.garmin.client import _to_garmin_step
from paceforge.models.plan import IntensityTarget, WorkoutStep, WorkoutStepType


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
        from paceforge.models.plan import Workout, WorkoutType

        brick = Workout(name="Brick", workout_type=WorkoutType.HYROX_MIXED)
        stations = Workout(name="Stations", workout_type=WorkoutType.CROSS_TRAINING)
        run = Workout(name="Easy", workout_type=WorkoutType.EASY_RUN)
        assert _sport_for(brick)["sportTypeKey"] == "fitness_equipment"
        assert _sport_for(stations)["sportTypeKey"] == "fitness_equipment"
        assert _sport_for(run)["sportTypeKey"] == "running"


def test_stepless_workout_gets_a_fallback_paced_step():
    from paceforge.garmin.client import _fallback_steps
    from paceforge.models.plan import Workout, WorkoutType

    wo = Workout(workout_type=WorkoutType.EASY_RUN, name="Easy shakeout",
                 estimated_distance_meters=5000)
    steps = _fallback_steps(wo, {"easy_pace": 300.0})
    assert len(steps) == 1
    assert steps[0].distance_meters == 5000
    assert steps[0].target_low and steps[0].target_high  # paced, so Garmin guides it
