"""Tests for the cycling engine (power zones, NP/IF/TSS, progression) and Garmin power steps."""

import pytest

from paceforge.engine.bike import (
    estimate_workout_tss,
    intensity_factor,
    normalized_power,
    power_zones,
    progression_update,
    ramp_test_ftp,
    suggest_next_level,
    tss,
)
from paceforge.garmin.client import _sport_for, _to_garmin_step
from paceforge.models.plan import (
    IntensityTarget,
    Workout,
    WorkoutStep,
    WorkoutStepType,
    WorkoutType,
)


class TestNormalizedPower:
    def test_constant_hour_at_ftp_gives_np_equal_to_power(self):
        assert normalized_power([200.0] * 3600) == pytest.approx(200.0)

    def test_if_is_one_at_ftp(self):
        assert intensity_factor(200.0, 200.0) == pytest.approx(1.0)

    def test_tss_is_100_for_an_hour_at_ftp(self):
        assert tss(3600, 200.0, 200.0) == pytest.approx(100.0)

    def test_np_exceeds_average_on_variable_power(self):
        samples = [100.0] * 1800 + [300.0] * 1800  # avg 200
        assert normalized_power(samples) > 200.0

    def test_short_sample_returns_plain_average(self):
        assert normalized_power([100.0, 200.0, 300.0]) == pytest.approx(200.0)


class TestFtpAndZones:
    def test_ramp_test_ftp_is_75_pct_of_best_1min(self):
        assert ramp_test_ftp(300) == 225

    def test_power_zones_z2_boundaries(self):
        assert power_zones(200)["Z2 Endurance"] == (110, 150)

    def test_power_zones_z4_spans_ftp(self):
        assert power_zones(200)["Z4 Threshold"] == (180, 210)

    def test_power_zones_z7_is_open_ended(self):
        assert power_zones(200)["Z7 Neuromuscular"] == (300, None)


class TestProgression:
    def test_pass_adds_0_4(self):
        assert progression_update(5.0, "pass") == pytest.approx(5.4)

    def test_struggled_adds_0_1(self):
        assert progression_update(5.0, "struggled") == pytest.approx(5.1)

    def test_failed_subtracts_0_5(self):
        assert progression_update(5.0, "failed") == pytest.approx(4.5)

    def test_clamps_at_floor(self):
        assert progression_update(1.2, "failed") == pytest.approx(1.0)

    def test_clamps_at_ceiling(self):
        assert progression_update(9.8, "pass") == pytest.approx(10.0)

    def test_suggest_next_level_adds_0_3(self):
        assert suggest_next_level(5.0) == pytest.approx(5.3)


class TestEstimateWorkoutTss:
    def test_hour_at_ftp_is_100(self):
        assert estimate_workout_tss([(3600, 200.0)], 200.0) == pytest.approx(100.0)


class TestGarminPowerStep:
    def test_power_step_serializes_as_power_zone_with_watts(self):
        step = WorkoutStep(
            step_type=WorkoutStepType.INTERVAL,
            duration_seconds=600,
            target_type=IntensityTarget.POWER,
            target_low=210.0,
            target_high=250.0,
        )
        result = _to_garmin_step(step)
        assert result.targetType["workoutTargetTypeId"] == 2  # power.zone
        assert result.targetType["workoutTargetTypeKey"] == "power.zone"
        assert result.targetValueOne == 210.0
        assert result.targetValueTwo == 250.0

    def test_bike_workout_pushes_as_cycling_sport(self):
        ride = Workout(name="Bike VO2", workout_type=WorkoutType.BIKE_WORKOUT, sport="bike")
        assert _sport_for(ride) == {"sportTypeId": 2, "sportTypeKey": "cycling"}

    def test_run_workout_still_pushes_as_running(self):
        run = Workout(name="Easy", workout_type=WorkoutType.EASY_RUN)
        assert _sport_for(run)["sportTypeKey"] == "running"
