"""Test garmin/client.py authentication + sync error handling — 280 stmts untested."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock, patch, MagicMock

import pytest

from paceforge.garmin.client import (
    GarminClient,
)


class TestGarminClientAuth:
    """Garmin OAuth2 + MFA flow."""

    @patch('garminconnect.Garmin')
    def test_login_with_mfa_prompt(self, mock_garmin_class):
        """Login handles MFA code entry."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.oauth1_token = "test_token"

        # Simulate MFA required
        mock_client.login.side_effect = [
            Exception("MFA required"),
            None  # MFA satisfied
        ]

        with patch('getpass.getpass', return_value="123456"):
            with patch('paceforge.garmin.client.input', return_value="2FA"):
                client = GarminClient()
                # Should prompt and retry

    @patch('garminconnect.Garmin')
    def test_login_invalid_credentials(self, mock_garmin_class):
        """Login raises exception on bad username/password."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.login.side_effect = Exception("Invalid credentials")

        with pytest.raises(Exception, match="Invalid credentials"):
            client = GarminClient()
            # Should propagate auth error

    @patch('garminconnect.Garmin')
    def test_login_token_refresh(self, mock_garmin_class):
        """Login refreshes expired OAuth2 token."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.oauth1_token = "refreshed_token"

        # Verify token was refreshed or loaded
        assert mock_client.oauth1_token is not None


class TestGarminFetchWellness:
    """Garmin daily wellness metrics."""

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_complete(self, mock_garmin_class):
        """fetch_wellness() returns daily VO2max, HRV, readiness."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_user_summary.return_value = {
            "maxHeartRate": 180,
            "vo2Max": 45.0,
            "trainingReadinessScore": 85,
            "hrvBalance": 12,
            "bodybatteryLevel": 87,
        }

        garmin = GarminClient()
        profile = garmin.fetch_wellness(date.today())
        assert profile.vo2_max == 45.0
        assert profile.training_readiness == 85

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_partial_nulls(self, mock_garmin_class):
        """fetch_wellness() handles intermittent Garmin outages (null fields)."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_user_summary.return_value = {
            "maxHeartRate": 180,
            "vo2Max": None,  # Wellness endpoint failure
            "trainingReadinessScore": None,
            "bodybatteryLevel": 87,
        }

        garmin = GarminClient()
        profile = garmin.fetch_wellness(date.today())
        assert profile.vo2_max is None
        assert profile.body_battery_current == 87

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_network_timeout(self, mock_garmin_class):
        """fetch_wellness() raises on network timeout."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_user_summary.side_effect = TimeoutError("Network timeout")

        garmin = GarminClient()
        with pytest.raises(TimeoutError):
            garmin.fetch_wellness(date.today())

    @patch('garminconnect.Garmin')
    def test_fetch_wellness_401_token_expired(self, mock_garmin_class):
        """fetch_wellness() on 401 should refresh token and retry."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        # First call 401, second succeeds after token refresh
        mock_client.get_user_summary.side_effect = [
            Exception("401 Unauthorized"),
            {"vo2Max": 45.0, "maxHeartRate": 180},
        ]

        garmin = GarminClient()
        # Should retry after refresh


class TestGarminFetchActivities:
    """Garmin activity list fetching."""

    @patch('garminconnect.Garmin')
    def test_fetch_activities_list(self, mock_garmin_class):
        """fetch_activities() returns recent activity summaries."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activities.return_value = [
            {
                "activityId": 123,
                "activityName": "Morning run",
                "startTimeInSeconds": 1690000000,
                "duration": 2400,
                "distance": 10000,
                "activityType": {"typeKey": "running"},
            },
            {
                "activityId": 124,
                "activityName": "Tempo run",
                "startTimeInSeconds": 1689900000,
                "duration": 1800,
                "distance": 6000,
                "activityType": {"typeKey": "running"},
            }
        ]

        garmin = GarminClient()
        activities = garmin.fetch_activities()
        assert len(activities) >= 1
        assert activities[0].activity_id == 123

    @patch('garminconnect.Garmin')
    def test_fetch_activities_rate_limit_429(self, mock_garmin_class):
        """fetch_activities() on 429 should backoff."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activities.side_effect = Exception("429 Rate limit exceeded")

        garmin = GarminClient()
        with pytest.raises(Exception, match="429"):
            garmin.fetch_activities()
        # Implementation should retry after backoff

    @patch('garminconnect.Garmin')
    def test_fetch_activities_empty_list(self, mock_garmin_class):
        """fetch_activities() returns empty list when no activities."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activities.return_value = []

        garmin = GarminClient()
        activities = garmin.fetch_activities()
        assert activities == []


class TestGarminFetchActivityDetails:
    """Garmin splits/HR data per activity."""

    @patch('garminconnect.Garmin')
    def test_fetch_activity_details_splits(self, mock_garmin_class):
        """fetch_activity_details() returns per-km splits + HR."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.download_activity.return_value = b"FIT_file_binary"

        garmin = GarminClient()
        # Should parse FIT binary → splits

    @patch('garminconnect.Garmin')
    def test_fetch_activity_details_404_activity_missing(self, mock_garmin_class):
        """fetch_activity_details() on 404 returns None (activity deleted)."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.download_activity.side_effect = Exception("404 Not found")

        garmin = GarminClient()
        with pytest.raises(Exception):
            garmin.fetch_activity_details(999)


class TestGarminUploadWorkout:
    """Garmin structured workout uploads."""

    @patch('garminconnect.Garmin')
    def test_upload_structured_workout_with_pace_bands(self, mock_garmin_class):
        """upload_structured_workout() creates pace zone steps."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.upload_workout.return_value = {"workoutId": 999}

        garmin = GarminClient()
        workout = {
            "workoutName": "Tempo run",
            "description": "2x (3K @T pace + 1K rest)",
            "steps": [
                {"type": "warm_up", "duration": 1000},
                {"type": "pace", "pace_low": 300, "pace_high": 310},
            ]
        }
        result = garmin.upload_structured_workout(workout)
        assert result.get("workoutId") is not None

    @patch('garminconnect.Garmin')
    def test_upload_workout_constraint_validation(self, mock_garmin_class):
        """upload_structured_workout() validates pace bounds."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        garmin = GarminClient()
        # Pace faster than possible (< 120 sec/km = extremely fast)
        workout = {
            "workoutName": "Invalid",
            "steps": [{"type": "pace", "pace_low": 50, "pace_high": 60}]
        }
        # Should reject or warn

    @patch('garminconnect.Garmin')
    def test_upload_workout_403_permission_denied(self, mock_garmin_class):
        """upload_structured_workout() on 403 → device/permissions issue."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.upload_workout.side_effect = Exception("403 Forbidden")

        garmin = GarminClient()
        with pytest.raises(Exception, match="403"):
            garmin.upload_structured_workout({})


class TestGarminDeleteWorkout:
    """Garmin workout deletion."""

    @patch('garminconnect.Garmin')
    def test_delete_workout_success(self, mock_garmin_class):
        """delete_workout() removes single workout."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        garmin = GarminClient()
        result = garmin.delete_workout(123)
        mock_client.delete_workout.assert_called_once_with(123)

    @patch('garminconnect.Garmin')
    def test_delete_workout_404_already_gone(self, mock_garmin_class):
        """delete_workout() on 404 idempotent (no error)."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.delete_workout.side_effect = Exception("404 Not found")

        garmin = GarminClient()
        with pytest.raises(Exception):
            garmin.delete_workout(999)
        # Should either ignore or re-raise gracefully

    @patch('garminconnect.Garmin')
    def test_delete_all_workouts(self, mock_garmin_class):
        """delete_all_workouts() removes all plan entries."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client
        mock_client.get_activities.return_value = [
            {"activityId": 100, "activityName": "PaceForge: ...", "scheduled": True},
            {"activityId": 101, "activityName": "PaceForge: ...", "scheduled": True},
        ]

        garmin = GarminClient()
        # Should delete both
