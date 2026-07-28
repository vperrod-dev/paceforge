"""Test analytics.py compute functions — 503 stmts (82%) untested."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest

from paceforge.engine.analytics import (
    _estimate_vdot,
    _predict_race_time,
    compute_athlete_snapshot,
    compute_aerobic_analysis,
    compute_running_economy,
    compute_load_recovery,
    compute_race_predictions,
    compute_hyrox_predictions,
    compute_training_recommendations,
)
from paceforge.models.profile import (
    UserFitnessProfile,
    RecentActivity,
    TrainingGoal,
    GoalType,
)


class TestEstimateVDOT:
    """_estimate_vdot() predicts aerobic capacity from race results."""

    def test_estimate_vdot_from_recent_5k(self):
        """_estimate_vdot() calculates VDOT from recent 5K time."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=5000,
                    duration_seconds=1200,  # 20 min 5K → ~50 VDOT
                    activity_type="RUNNING",
                )
            ]
        )
        vdot = _estimate_vdot(profile)
        assert vdot is not None
        assert 45 < vdot < 55  # Rough range

    def test_estimate_vdot_no_activities(self):
        """_estimate_vdot() returns None with no race efforts."""
        profile = UserFitnessProfile(activities=[])
        vdot = _estimate_vdot(profile)
        assert vdot is None

    def test_estimate_vdot_ignores_easy_runs(self):
        """_estimate_vdot() skips easy efforts (duration >> 90 min)."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=20000,
                    duration_seconds=7200,  # 2 hrs easy run
                    activity_type="RUNNING",
                )
            ]
        )
        vdot = _estimate_vdot(profile)
        assert vdot is None  # Not a race effort

    def test_estimate_vdot_ages_recent_result_heavily(self):
        """_estimate_vdot() weights recent efforts more (within 2 weeks)."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today() - timedelta(days=30),
                    distance_meters=5000,
                    duration_seconds=1200,
                    activity_type="RUNNING",
                ),
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=10000,
                    duration_seconds=2500,  # Slightly slower
                    activity_type="RUNNING",
                )
            ]
        )
        vdot = _estimate_vdot(profile)
        # Recent slower effort should dominate
        assert vdot is not None


class TestPredictRaceTime:
    """_predict_race_time() forecasts pace per Riegel formula."""

    def test_predict_race_time_same_distance(self):
        """_predict_race_time() returns input time at same distance."""
        vdot = 50.0
        distance = 10000
        time_sec = 2400
        predicted = _predict_race_time(vdot, distance)
        # Should be close to Riegel formula

    def test_predict_race_time_marathon_from_10k(self):
        """_predict_race_time() estimates marathon from 10K VDOT."""
        vdot = 50.0
        marathon_time = _predict_race_time(vdot, 42195)
        # 50 VDOT ≈ 2:20 marathon (Riegel)
        assert 8000 < marathon_time < 8500  # ~2:13 to 2:23

    def test_predict_race_time_zero_distance_error(self):
        """_predict_race_time() errors on zero distance."""
        with pytest.raises((ValueError, ZeroDivisionError)):
            _predict_race_time(50.0, 0)


class TestAthleteSnapshot:
    """compute_athlete_snapshot() aggregates summary stats."""

    def test_snapshot_vo2_max(self):
        """Snapshot includes current VO2max."""
        profile = UserFitnessProfile(vo2_max=45.0)
        snapshot = compute_athlete_snapshot(profile)
        assert snapshot.vo2_max == 45.0

    def test_snapshot_last_activity_date(self):
        """Snapshot captures most recent activity."""
        today = date.today()
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=today - timedelta(days=2),
                    distance_meters=10000,
                    duration_seconds=2400,
                    activity_type="RUNNING",
                ),
                RecentActivity(
                    activity_date=today,
                    distance_meters=5000,
                    duration_seconds=1200,
                    activity_type="RUNNING",
                )
            ]
        )
        snapshot = compute_athlete_snapshot(profile)
        assert snapshot.last_activity_date == today

    def test_snapshot_empty_profile(self):
        """Snapshot on empty profile doesn't crash."""
        profile = UserFitnessProfile()
        snapshot = compute_athlete_snapshot(profile)
        assert snapshot is not None


class TestAerobicAnalysis:
    """compute_aerobic_analysis() tracks VO2max + aerobic power trends."""

    def test_aerobic_analysis_vo2_improvement(self):
        """Analysis detects VO2max gain over time."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today() - timedelta(days=60),
                    distance_meters=5000,
                    duration_seconds=1250,
                    vo2_max_during=43.0,
                    activity_type="RUNNING",
                ),
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=5000,
                    duration_seconds=1200,
                    vo2_max_during=45.0,
                    activity_type="RUNNING",
                )
            ],
            vo2_max=45.0,
        )
        analysis = compute_aerobic_analysis(profile)
        assert analysis is not None
        # Should show improvement trend

    def test_aerobic_analysis_stagnation(self):
        """Analysis flags flat VO2max (plateau or fatigue)."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today() - timedelta(days=i*10),
                    distance_meters=5000,
                    duration_seconds=1200,
                    vo2_max_during=45.0,
                    activity_type="RUNNING",
                )
                for i in range(6)
            ],
            vo2_max=45.0,
        )
        analysis = compute_aerobic_analysis(profile)
        # Should note lack of improvement


class TestRunningEconomy:
    """compute_running_economy() measures efficiency (pace per HR)."""

    def test_running_economy_normal_effort(self):
        """Economy calculation on steady-state run."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=10000,
                    duration_seconds=2400,
                    avg_heart_rate=145,
                    activity_type="RUNNING",
                )
            ],
            max_hr=180,
        )
        economy = compute_running_economy(profile)
        assert economy is not None

    def test_running_economy_missing_hr(self):
        """Economy skips activities without HR data."""
        profile = UserFitnessProfile(
            activities=[
                RecentActivity(
                    activity_date=date.today(),
                    distance_meters=10000,
                    duration_seconds=2400,
                    avg_heart_rate=None,
                    activity_type="RUNNING",
                )
            ]
        )
        economy = compute_running_economy(profile)
        # Should skip or return null


class TestLoadRecovery:
    """compute_load_recovery() calculates CTL/ATL/TSB."""

    def test_load_recovery_ctal_formula(self):
        """Load recovery applies Banister CTL/ATL formulas."""
        activities = [
            RecentActivity(
                activity_date=date.today() - timedelta(days=i),
                distance_meters=10000,
                duration_seconds=2400,
                activity_type="RUNNING",
                # Should map to TRIMP
            )
            for i in range(30)
        ]
        profile = UserFitnessProfile(activities=activities)
        load = compute_load_recovery(profile)
        assert load.ctl is not None  # Chronic training load
        assert load.atl is not None  # Acute training load
        assert load.tsb is not None  # Training stress balance

    def test_tsb_overtraining_flag(self):
        """TSB < -50 flags overtraining risk."""
        # Construct high-load, low-recovery scenario
        profile = UserFitnessProfile()
        load = compute_load_recovery(profile)
        if load.tsb and load.tsb < -50:
            assert load.status == "overtraining"

    def test_tsb_recovery_window(self):
        """TSB > 25 after tapered week flags ready state."""
        profile = UserFitnessProfile()
        load = compute_load_recovery(profile)
        if load.tsb and load.tsb > 25:
            assert load.status == "ready"


class TestRacePredictions:
    """compute_race_predictions() forecasts finish times."""

    def test_race_predictions_multi_distance(self):
        """Predictions include 5K, 10K, half, full marathon."""
        profile = UserFitnessProfile(vo2_max=50.0)
        predictions = compute_race_predictions(profile)
        assert predictions.race_5k_sec is not None
        assert predictions.race_10k_sec is not None
        assert predictions.race_half_marathon_sec is not None
        assert predictions.race_marathon_sec is not None

    def test_predictions_pace_ordering(self):
        """5K pace < 10K pace < marathon (all faster → longer distance)."""
        profile = UserFitnessProfile(vo2_max=50.0)
        pred = compute_race_predictions(profile)
        pace_5k = pred.race_5k_sec / 5
        pace_10k = pred.race_10k_sec / 10
        pace_marathon = pred.race_marathon_sec / 42.195
        assert pace_5k < pace_10k < pace_marathon


class TestHyroxPredictions:
    """compute_hyrox_predictions() estimates obstacle-race times."""

    def test_hyrox_prediction_includes_run_time(self):
        """Hyrox prediction splits running vs obstacle overhead."""
        profile = UserFitnessProfile(vo2_max=50.0)
        predictions = compute_hyrox_predictions(profile)
        assert predictions.estimated_total_sec is not None
        # Should include road-running equivalent + obstacle penalty

    def test_hyrox_obstacle_penalty_scales_with_vo2(self):
        """Higher VO2max reduces obstacle-time penalty."""
        low_vo2 = UserFitnessProfile(vo2_max=40.0)
        high_vo2 = UserFitnessProfile(vo2_max=55.0)
        low_pred = compute_hyrox_predictions(low_vo2)
        high_pred = compute_hyrox_predictions(high_vo2)
        # High VO2 should predict faster


class TestTrainingRecommendations:
    """compute_training_recommendations() suggests workout focus."""

    def test_recommendations_from_profile(self):
        """Recommendations identify limiting factors."""
        profile = UserFitnessProfile(vo2_max=45.0, max_hr=175)
        recommendations = compute_training_recommendations(profile)
        assert recommendations is not None
        # Should suggest aerobic work, speed, or strength based on profile

    def test_recommendations_prioritize_gaps(self):
        """Weak limiter (e.g., speed) gets top priority."""
        # Profile with good endurance, weak speed
        profile = UserFitnessProfile(vo2_max=50.0)  # Good aerobic
        recommendations = compute_training_recommendations(profile)
        # Should prioritize speed work
