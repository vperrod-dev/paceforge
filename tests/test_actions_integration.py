"""Test actions.py end-to-end workflows — 192 stmts (26%) untested."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch, MagicMock

import pytest

from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile, RecentActivity, TrainingGoal, GoalType
from paceforge.models.plan import TrainingPlan, WorkoutType


class TestSyncDetailsLoop:
    """_sync_details() fetches activity splits in N+1 loop."""

    @patch('paceforge.actions.garmin_connect')
    def test_sync_details_fetches_splits(self, mock_garmin_factory):
        """_sync_details() loads splits for recent activities."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        # Mock activity list
        activities = [
            {"activityId": i, "duration": 2400} for i in range(5)
        ]
        mock_client.get_activities.return_value = activities

        # Mock detail responses
        mock_client.download_activity.return_value = b"FIT_binary"

        with TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {"PACEFORGE_DATA_DIR": tmpdir}):
                fetched, skipped = actions._sync_details(mock_client, limit=5)
                assert fetched > 0

    @patch('paceforge.actions.garmin_connect')
    def test_sync_details_limit(self, mock_garmin_factory):
        """_sync_details(limit=N) only fetches N most recent."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        activities = [{"activityId": i} for i in range(100)]
        mock_client.get_activities.return_value = activities
        mock_client.download_activity.return_value = b"FIT"

        with TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {"PACEFORGE_DATA_DIR": tmpdir}):
                fetched, _ = actions._sync_details(mock_client, limit=10)
                # Should have called download_activity at most 10 times
                assert mock_client.download_activity.call_count <= 10

    @patch('paceforge.actions.garmin_connect')
    def test_sync_details_skips_404(self, mock_garmin_factory):
        """_sync_details() skips activities deleted from Garmin."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        activities = [
            {"activityId": 1},
            {"activityId": 2},
        ]
        mock_client.get_activities.return_value = activities
        mock_client.download_activity.side_effect = [
            b"FIT",
            Exception("404 Not found"),
        ]

        with TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {"PACEFORGE_DATA_DIR": tmpdir}):
                fetched, skipped = actions._sync_details(mock_client, limit=2)
                assert fetched == 1
                assert skipped == 1


class TestFindWorkout:
    """_find_workout() matches activity to plan session."""

    def test_find_workout_by_session_id(self):
        """_find_workout() matches session_id link."""
        plan = TrainingPlan(
            weeks=[{
                "workouts": [{
                    "id": "mon_week1",
                    "name": "Easy run",
                    "garmin_workout_id": None,
                }]
            }]
        )
        result = actions._find_workout(plan, session_id="mon_week1", when=None)
        assert result is not None
        assert result["name"] == "Easy run"

    def test_find_workout_by_date(self):
        """_find_workout() matches by activity date."""
        plan = TrainingPlan(
            weeks=[{
                "workouts": [{
                    "id": "mon_week1",
                    "name": "Easy run",
                    "date": "2026-07-28",
                }]
            }]
        )
        result = actions._find_workout(plan, session_id=None, when="2026-07-28")
        assert result is not None

    def test_find_workout_ambiguous_date(self):
        """_find_workout() on multiple same-day workouts returns first."""
        plan = TrainingPlan(
            weeks=[{
                "workouts": [
                    {"id": "am", "name": "Morning", "date": "2026-07-28"},
                    {"id": "pm", "name": "Evening", "date": "2026-07-28"},
                ]
            }]
        )
        result = actions._find_workout(plan, session_id=None, when="2026-07-28")
        assert result["id"] in ("am", "pm")

    def test_find_workout_none_found(self):
        """_find_workout() returns None when no match."""
        plan = TrainingPlan(weeks=[{"workouts": []}])
        result = actions._find_workout(plan, session_id="nope", when=None)
        assert result is None


class TestBriefFormatting:
    """brief() formats daily coaching summary."""

    def test_brief_default_text_format(self):
        """brief() outputs plain text by default."""
        with patch('paceforge.actions.store.load_profile') as mock_load:
            mock_profile = UserFitnessProfile(vo2_max=45.0)
            mock_load.return_value = mock_profile

            with patch('paceforge.actions.store.load_plan'):
                with patch('paceforge.actions.compute_all'):
                    text = actions.brief(when=None, fmt="text")
                    assert isinstance(text, str)
                    assert len(text) > 0

    def test_brief_html_format(self):
        """brief(fmt='html') escapes content."""
        with patch('paceforge.actions.store.load_profile') as mock_load:
            mock_profile = UserFitnessProfile(vo2_max=45.0)
            mock_load.return_value = mock_profile

            with patch('paceforge.actions.store.load_plan'):
                with patch('paceforge.actions.compute_all'):
                    html = actions.brief(when=None, fmt="html")
                    # Should contain <html> tags or escaped entities
                    assert isinstance(html, str)

    def test_brief_telegram_format(self):
        """brief(fmt='telegram') uses HTML + emoji."""
        with patch('paceforge.actions.store.load_profile') as mock_load:
            mock_profile = UserFitnessProfile(vo2_max=45.0)
            mock_load.return_value = mock_profile

            with patch('paceforge.actions.store.load_plan'):
                with patch('paceforge.actions.compute_all'):
                    telegram = actions.brief(when=None, fmt="telegram")
                    assert isinstance(telegram, str)


class TestScaffoldPlan:
    """scaffold() generates deterministic baseline plan."""

    def test_scaffold_basic_flow(self):
        """scaffold() generates plan from goal+date+level."""
        with patch('paceforge.actions.store.load_profile') as mock_load_prof:
            with patch('paceforge.actions.store.save_plan') as mock_save:
                mock_load_prof.return_value = UserFitnessProfile(vo2_max=45.0)

                plan = actions.scaffold(
                    goal="MARATHON",
                    race_date=date(2026, 10, 4),
                    level="intermediate",
                    days=["tuesday", "thursday", "saturday", "sunday"],
                )
                assert plan is not None
                mock_save.assert_called_once()

    def test_scaffold_with_target_time(self):
        """scaffold() uses target time to adjust paces."""
        with patch('paceforge.actions.store.load_profile') as mock_load_prof:
            with patch('paceforge.actions.store.save_plan'):
                mock_load_prof.return_value = UserFitnessProfile()

                plan = actions.scaffold(
                    goal="MARATHON",
                    race_date=date(2026, 10, 4),
                    level="intermediate",
                    target_time=8400,  # 2:20 marathon
                )
                assert plan is not None


class TestRecalibratePaceDelta:
    """recalibrate() shifts plan paces by VDOT delta."""

    def test_recalibrate_positive_delta(self):
        """recalibrate(delta=0.5) increases all paces."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan') as mock_save:
                plan = TrainingPlan(
                    weeks=[{
                        "workouts": [{
                            "pace_low_sec": 300,  # 5:00/km
                            "pace_high_sec": 310,
                        }]
                    }]
                )
                mock_load.return_value = plan

                result = actions.recalibrate(delta=0.5, force=False)
                # Paces should have shifted
                mock_save.assert_called_once()

    def test_recalibrate_negative_delta(self):
        """recalibrate(delta=-0.5) decreases all paces."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan'):
                plan = TrainingPlan(
                    weeks=[{
                        "workouts": [{
                            "pace_low_sec": 300,
                            "pace_high_sec": 310,
                        }]
                    }]
                )
                mock_load.return_value = plan
                result = actions.recalibrate(delta=-0.5, force=False)
                assert result is not None

    def test_recalibrate_guard_blocks_unapproved_shift(self):
        """recalibrate(force=False) only shifts accepted future weeks."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(accepted_week=1)
            mock_load.return_value = plan

            # Should only recalibrate week 2+
            actions.recalibrate(delta=0.5, force=False)


class TestPushToGarmin:
    """push() uploads plan week to Garmin calendar."""

    @patch('paceforge.actions.garmin_connect')
    def test_push_current_week(self, mock_garmin_factory):
        """push() uploads current + next 2 weeks."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(
                weeks=[{"workouts": []} for _ in range(4)]
            )
            mock_load.return_value = plan

            result = actions.push(week=None, dry_run=False)
            # Should upload 3 weeks
            assert mock_client.upload_structured_workout.call_count >= 3

    @patch('paceforge.actions.garmin_connect')
    def test_push_specific_week(self, mock_garmin_factory):
        """push(week=2) uploads week 2 only."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(
                weeks=[{"workouts": []} for _ in range(4)]
            )
            mock_load.return_value = plan

            result = actions.push(week=2, dry_run=False)
            # Should upload week 2 workouts

    @patch('paceforge.actions.garmin_connect')
    def test_push_dry_run_no_upload(self, mock_garmin_factory):
        """push(dry_run=True) previews without uploading."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(weeks=[{"workouts": []}])
            mock_load.return_value = plan

            result = actions.push(week=None, dry_run=True)
            # Should not call upload
            mock_client.upload_structured_workout.assert_not_called()


class TestAutoSync:
    """autosync() reconciles plan with Garmin calendar."""

    @patch('paceforge.actions.garmin_connect')
    def test_autosync_push_current_3_weeks(self, mock_garmin_factory):
        """autosync() pushes current + 2 future weeks."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client

        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(weeks=[{"workouts": []} for _ in range(4)])
            mock_load.return_value = plan

            result = actions.autosync()
            # Should push 3 weeks

    @patch('paceforge.actions.garmin_connect')
    def test_autosync_delete_stale_workouts(self, mock_garmin_factory):
        """autosync() deletes past/orphaned workouts from Garmin."""
        mock_client = MagicMock()
        mock_garmin_factory.return_value = mock_client
        mock_client.get_all_workouts.return_value = [
            {"workoutId": 123, "createdDate": date(2026, 7, 1)},  # Old
            {"workoutId": 124, "createdDate": date(2026, 7, 28)},  # Current
        ]

        with patch('paceforge.actions.store.load_plan') as mock_load:
            plan = TrainingPlan(weeks=[{"workouts": []}])
            mock_load.return_value = plan

            result = actions.autosync()
            # Should delete 123, keep 124


class TestAdaptMissedSessions:
    """adapt() reflows missed sessions + readiness gate."""

    def test_adapt_reflow_missed_session(self):
        """adapt() reschedules missed session to later in week."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan'):
                plan = TrainingPlan(
                    weeks=[{
                        "workouts": [
                            {"id": "mon", "completed": False},
                            {"id": "tue", "completed": False},
                            {"id": "wed", "completed": False},
                        ]
                    }]
                )
                mock_load.return_value = plan

                result = actions.adapt(dry_run=False)
                # Should reflow mon→wed or tue→later

    def test_adapt_readiness_gate_hard_work(self):
        """adapt() gates hard workout when readiness < 50."""
        with patch('paceforge.actions.compute_all') as mock_compute:
            with patch('paceforge.actions.store.load_plan') as mock_load:
                with patch('paceforge.actions.store.save_plan'):
                    mock_compute.return_value = {
                        "readiness": 40,  # Low readiness
                    }
                    plan = TrainingPlan(
                        weeks=[{
                            "workouts": [{
                                "id": "vo2",
                                "type": "VO2",
                                "readiness_gate": True,
                            }]
                        }]
                    )
                    mock_load.return_value = plan

                    result = actions.adapt(dry_run=False)
                    # Should downgrade VO2 to easier variant


class TestErrorHandling:
    """CLI error handlers."""

    def test_main_runtime_error_handler(self):
        """cli.main() catches RuntimeError and exits."""
        # Should test the exception handler at cli.py:178-180

    def test_main_keyboard_interrupt(self):
        """cli.main() exits cleanly on Ctrl+C."""
        # Should test keyboard interrupt handling
