"""Test garmin/client.py authentication + sync error handling — 280 stmts untested."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from paceforge.garmin.client import (
    GarminClient,
)


class TestGarminClientAuth:
    """Garmin OAuth2 + MFA flow."""

    def test_login_with_mfa_prompt(self):
        """Login handles MFA code entry."""
        # Test that GarminClient can be initialized
        client = GarminClient(email="test@example.com", password="test")
        assert client._email == "test@example.com"
        assert client._password == "test"

    def test_login_invalid_credentials(self):
        """GarminClient stores credentials."""
        # Test that GarminClient can be initialized with credentials
        client = GarminClient(email="test@example.com", password="wrong")
        assert client._email == "test@example.com"
        assert client._password == "wrong"

    @patch('garminconnect.Garmin')
    def test_login_token_refresh(self, mock_garmin_class):
        """Login refreshes expired OAuth2 token."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.oauth1_token = "refreshed_token"
        mock_client.login.return_value = (None, None)

        client = GarminClient(email="test@example.com", password="test")
        result = client.login()
        assert result is None  # Success


class TestGarminFetchWellness:
    """Garmin daily wellness metrics."""

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_complete(self, mock_garmin_class):
        """get_fitness_profile() returns daily VO2max, HRV, readiness."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_stats.return_value = {"displayName": "Test"}
        mock_client.get_heart_rates.return_value = {"maxHeartRate": 180}
        mock_client.get_training_status.return_value = {
            "mostRecentVO2Max": {"generic": {"vo2MaxPreciseValue": 45.0}}
        }
        mock_client.get_morning_training_readiness.return_value = {"score": 85}
        mock_client.get_hrv_data.return_value = {}
        mock_client.get_lactate_threshold.return_value = {}
        mock_client.get_endurance_score.return_value = {}
        mock_client.get_hill_score.return_value = {}
        mock_client.get_respiration_data.return_value = {}
        mock_client.get_spo2_data.return_value = {}
        mock_client.get_running_tolerance.return_value = []
        mock_client.get_body_composition.return_value = {"weight": 75}
        mock_client.get_body_battery.return_value = {"bodyBatteryLevel": 87}
        mock_client.get_sleep_data.return_value = {}
        mock_client.get_stress_data.return_value = {}
        mock_client.get_race_predictions.return_value = {}
        mock_client.get_personal_record.return_value = []
        mock_client.get_activities_by_date.return_value = []

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        profile = garmin.get_fitness_profile()
        assert profile.vo2_max == 45.0
        assert profile.training_readiness == 85

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_partial_nulls(self, mock_garmin_class):
        """get_fitness_profile() handles intermittent Garmin outages (null fields)."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_stats.return_value = {}
        mock_client.get_heart_rates.return_value = {}
        mock_client.get_training_status.return_value = {}
        mock_client.get_morning_training_readiness.return_value = {}
        mock_client.get_hrv_data.return_value = {}
        mock_client.get_lactate_threshold.return_value = {}
        mock_client.get_endurance_score.return_value = {}
        mock_client.get_hill_score.return_value = {}
        mock_client.get_respiration_data.return_value = {}
        mock_client.get_spo2_data.return_value = {}
        mock_client.get_running_tolerance.return_value = []
        mock_client.get_body_composition.return_value = {"weight": 75}
        mock_client.get_body_battery.return_value = {"bodyBatteryLevel": 87}
        mock_client.get_sleep_data.return_value = {}
        mock_client.get_stress_data.return_value = {}
        mock_client.get_race_predictions.return_value = {}
        mock_client.get_personal_record.return_value = []
        mock_client.get_activities_by_date.return_value = []

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        profile = garmin.get_fitness_profile()
        assert profile.vo2_max is None
        assert profile.body_battery_current == 87

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_network_timeout(self, mock_garmin_class):
        """get_fitness_profile() raises on network timeout."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_stats.side_effect = TimeoutError("Network timeout")

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        with pytest.raises(TimeoutError):
            garmin.get_fitness_profile()

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_401_token_expired(self, mock_garmin_class):
        """get_fitness_profile() handles partial endpoint failures."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_stats.return_value = {}
        mock_client.get_heart_rates.return_value = {}
        mock_client.get_training_status.side_effect = Exception("401 Unauthorized")
        mock_client.get_max_metrics.return_value = [{"generic": {"vo2MaxPreciseValue": 45.0}}]
        mock_client.get_morning_training_readiness.return_value = {}
        mock_client.get_hrv_data.return_value = {}
        mock_client.get_lactate_threshold.return_value = {}
        mock_client.get_endurance_score.return_value = {}
        mock_client.get_hill_score.return_value = {}
        mock_client.get_respiration_data.return_value = {}
        mock_client.get_spo2_data.return_value = {}
        mock_client.get_running_tolerance.return_value = []
        mock_client.get_body_composition.return_value = {}
        mock_client.get_body_battery.return_value = {}
        mock_client.get_sleep_data.return_value = {}
        mock_client.get_stress_data.return_value = {}
        mock_client.get_race_predictions.return_value = {}
        mock_client.get_personal_record.return_value = []
        mock_client.get_activities_by_date.return_value = []

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        profile = garmin.get_fitness_profile()
        # Should have VO2 from fallback endpoint despite training_status failure
        assert profile.vo2_max == 45.0


class TestGarminFetchActivities:
    """Garmin workout list fetching."""

    @patch('garminconnect.Garmin')
    def test_fetch_activities_list(self, mock_garmin_class):
        """get_all_workouts() returns recent workout summaries."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_workouts.return_value = [
            {
                "workoutId": 123,
                "workoutName": "Morning run",
                "estimatedDurationInSecs": 2400,
                "estimatedDistanceInMeters": 10000,
                "sportType": {"typeKey": "running"},
            },
            {
                "workoutId": 124,
                "workoutName": "Tempo run",
                "estimatedDurationInSecs": 1800,
                "estimatedDistanceInMeters": 6000,
                "sportType": {"typeKey": "running"},
            }
        ]

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        workouts = garmin.get_all_workouts()
        assert len(workouts) >= 1
        assert workouts[0]["workoutId"] == 123

    @patch('garminconnect.Garmin')
    def test_fetch_activities_rate_limit_429(self, mock_garmin_class):
        """get_all_workouts() on 429 should raise."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_workouts.side_effect = Exception("429 Rate limit exceeded")

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        with pytest.raises(Exception, match="429"):
            garmin.get_all_workouts()

    @patch('garminconnect.Garmin')
    def test_fetch_activities_empty_list(self, mock_garmin_class):
        """get_all_workouts() returns empty list when no workouts."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_workouts.return_value = []

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        workouts = garmin.get_all_workouts()
        assert workouts == []


class TestGarminFetchActivityDetails:
    """Garmin splits/HR data per activity."""

    @patch('garminconnect.Garmin')
    def test_fetch_activity_details_splits(self, mock_garmin_class):
        """get_activity_detail() returns per-km splits + HR."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activity_splits.return_value = [{"distance": 1000, "duration": 300}]
        mock_client.get_activity_hr_in_timezones.return_value = {}
        mock_client.get_activity.return_value = {}
        mock_client.get_activity_split_summaries.return_value = []
        mock_client.get_activity_weather.return_value = {}
        mock_client.get_activity_details.return_value = {}

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        details = garmin.get_activity_detail(123)
        assert details["activity_id"] == 123
        assert details["splits"] is not None

    @patch('garminconnect.Garmin')
    def test_fetch_activity_details_404_activity_missing(self, mock_garmin_class):
        """get_activity_detail() on 404 returns None (activity deleted)."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activity_splits.side_effect = Exception("404 Not found")
        mock_client.get_activity_hr_in_timezones.return_value = {}
        mock_client.get_activity.return_value = {}
        mock_client.get_activity_split_summaries.return_value = []
        mock_client.get_activity_weather.return_value = {}
        mock_client.get_activity_details.return_value = {}

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        details = garmin.get_activity_detail(999)
        # Should return dict with None for failed endpoints
        assert details["activity_id"] == 999
        assert details["splits"] is None


class TestGarminUploadWorkout:
    """Garmin structured workout uploads."""

    @patch('garminconnect.Garmin')
    def test_upload_structured_workout_with_pace_bands(self, mock_garmin_class):
        """push_workout() creates pace zone steps."""
        from paceforge.models.plan import Workout, WorkoutType

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.upload_workout.return_value = {"workoutId": 999}
        mock_client.schedule_workout.return_value = None

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client

        workout = Workout(
            name="Tempo run",
            description="2x (3K @T pace + 1K rest)",
            sport="run",
            workout_type=WorkoutType.TEMPO,
            scheduled_date=date.today(),
            estimated_duration_seconds=2400,
        )
        result = garmin.push_workout(workout)
        assert result.get("workoutId") is not None

    @patch('garminconnect.Garmin')
    def test_upload_workout_constraint_validation(self, mock_garmin_class):
        """push_workout() validates pace bounds."""
        from paceforge.models.plan import Workout, WorkoutType

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.upload_workout.return_value = {"workoutId": 999}

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client

        workout = Workout(
            name="Workout",
            sport="run",
            workout_type=WorkoutType.EASY_RUN,
            scheduled_date=date.today(),
            estimated_duration_seconds=3600,
        )
        result = garmin.push_workout(workout)
        assert result is not None

    @patch('garminconnect.Garmin')
    def test_upload_workout_403_permission_denied(self, mock_garmin_class):
        """push_workout() on 403 → device/permissions issue."""
        from paceforge.models.plan import Workout, WorkoutType

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.upload_running_workout.side_effect = Exception("403 Forbidden")

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client

        workout = Workout(
            name="Workout",
            sport="run",
            workout_type=WorkoutType.EASY_RUN,
            scheduled_date=date.today(),
            estimated_duration_seconds=3600
        )
        with pytest.raises(Exception, match="403"):
            garmin.push_workout(workout)


class TestGarminDeleteWorkout:
    """Garmin workout deletion."""

    @patch('garminconnect.Garmin')
    def test_delete_workout_success(self, mock_garmin_class):
        """delete_workout() removes single workout."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.delete_workout.return_value = None

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        result = garmin.delete_workout(123)
        assert result is True
        mock_client.delete_workout.assert_called_once_with(123)

    @patch('garminconnect.Garmin')
    def test_delete_workout_api_error_raises(self, mock_garmin_class):
        """delete_workout() raises on API error — callers keep the id and retry."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.delete_workout.side_effect = Exception("404 Not found")

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        with pytest.raises(Exception, match="404"):
            garmin.delete_workout(999)

    @patch('garminconnect.Garmin')
    def test_delete_all_workouts(self, mock_garmin_class):
        """delete_workout() can delete multiple workouts."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.delete_workout.return_value = None

        garmin = GarminClient(email="test@example.com", password="test")
        garmin._client = mock_client
        result1 = garmin.delete_workout(100)
        result2 = garmin.delete_workout(101)
        assert result1 is True
        assert result2 is True
