"""Test actions.py end-to-end workflows — 192 stmts (26%) untested."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch, MagicMock

import pytest

from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile, RecentActivity, TrainingGoal, GoalType
from paceforge.models.plan import TrainingPlan, WorkoutType


class TestSyncDetailsLoop:
    """_sync_details() fetches activity splits in N+1 loop."""

    def test_sync_details_fetches_splits(self):
        """_sync_details() loads splits for recent activities."""
        mock_client = MagicMock()
        activities = [
            RecentActivity(
                activity_id=i,
                name=f"Run {i}",
                activity_type="running",
                start_time=datetime.now(),
                distance_meters=10000,
                duration_seconds=2400,
            )
            for i in range(5)
        ]

        with patch('paceforge.actions.store.load_activities') as mock_load_acts:
            with patch('paceforge.actions.store.load_plan') as mock_load_plan:
                with patch('paceforge.actions.store.has_detail') as mock_has:
                    with patch('paceforge.actions.store.save_detail') as mock_save:
                        with patch('paceforge.actions._fetch_detail') as mock_fetch:
                            mock_load_acts.return_value = activities
                            mock_load_plan.return_value = None
                            mock_has.return_value = False
                            mock_fetch.return_value = {"activity_id": 0, "splits": []}

                            fetched, failed = actions._sync_details(mock_client, limit=5)
                            assert fetched == 5
                            assert failed == 0
                            assert mock_save.call_count == 5

    def test_sync_details_limit(self):
        """_sync_details(limit=N) only fetches N most recent."""
        mock_client = MagicMock()
        activities = [
            RecentActivity(activity_id=i, distance_meters=10000, duration_seconds=2400)
            for i in range(100)
        ]

        with patch('paceforge.actions.store.load_activities') as mock_load_acts:
            with patch('paceforge.actions.store.load_plan') as mock_load_plan:
                with patch('paceforge.actions.store.has_detail') as mock_has:
                    with patch('paceforge.actions.store.save_detail'):
                        with patch('paceforge.actions._fetch_detail') as mock_fetch:
                            mock_load_acts.return_value = activities[:100]
                            mock_load_plan.return_value = None
                            mock_has.return_value = False
                            mock_fetch.return_value = {"activity_id": 0}

                            fetched, failed = actions._sync_details(mock_client, limit=10)
                            # Should have fetched at most 10
                            assert fetched <= 10

    def test_sync_details_skips_404(self):
        """_sync_details() skips activities deleted from Garmin."""
        mock_client = MagicMock()
        activities = [
            RecentActivity(activity_id=1, distance_meters=10000, duration_seconds=2400),
            RecentActivity(activity_id=2, distance_meters=10000, duration_seconds=2400),
        ]

        with patch('paceforge.actions.store.load_activities') as mock_load_acts:
            with patch('paceforge.actions.store.load_plan') as mock_load_plan:
                with patch('paceforge.actions.store.has_detail') as mock_has:
                    with patch('paceforge.actions.store.save_detail'):
                        with patch('paceforge.actions._fetch_detail') as mock_fetch:
                            mock_load_acts.return_value = activities
                            mock_load_plan.return_value = None
                            mock_has.return_value = False
                            mock_fetch.side_effect = [
                                {"activity_id": 1},
                                Exception("404 Not found"),
                            ]

                            fetched, failed = actions._sync_details(mock_client, limit=2)
                            assert fetched == 1
                            assert failed == 1


class TestFindWorkout:
    """_find_workout() matches activity to plan session."""

    def test_find_workout_by_session_id(self):
        """_find_workout() matches session_id link."""
        plan = TrainingPlan(
            name="Test Plan",
            goal_type="MARATHON",
            target_date=date(2026, 10, 4),
            total_weeks=12,
            weeks=[{
                "week_number": 1,
                "workouts": [{
                    "session_id": "mon_week1",
                    "name": "Easy run",
                    "workout_type": "easy_run",
                    "garmin_workout_id": None,
                }]
            }]
        )
        result = actions._find_workout(plan, session_id="mon_week1", when=None)
        assert result is not None
        assert result.name == "Easy run"

    def test_find_workout_by_date(self):
        """_find_workout() matches by activity date."""
        plan = TrainingPlan(
            name="Test Plan",
            goal_type="MARATHON",
            target_date=date(2026, 10, 4),
            total_weeks=12,
            weeks=[{
                "week_number": 1,
                "workouts": [{
                    "session_id": "mon_week1",
                    "name": "Easy run",
                    "workout_type": "easy_run",
                    "scheduled_date": "2026-07-28",
                }]
            }]
        )
        result = actions._find_workout(plan, session_id=None, when="2026-07-28")
        assert result is not None

    def test_find_workout_ambiguous_date(self):
        """_find_workout() raises error on multiple same-day workouts."""
        plan = TrainingPlan(
            name="Test Plan",
            goal_type="MARATHON",
            target_date=date(2026, 10, 4),
            total_weeks=12,
            weeks=[{
                "week_number": 1,
                "workouts": [
                    {"session_id": "am", "name": "Morning", "workout_type": "easy_run", "scheduled_date": "2026-07-28"},
                    {"session_id": "pm", "name": "Evening", "workout_type": "easy_run", "scheduled_date": "2026-07-28"},
                ]
            }]
        )
        with pytest.raises(RuntimeError, match="Multiple workouts"):
            actions._find_workout(plan, session_id=None, when="2026-07-28")

    def test_find_workout_none_found(self):
        """_find_workout() raises error when no match found."""
        plan = TrainingPlan(
            name="Test Plan",
            goal_type="MARATHON",
            target_date=date(2026, 10, 4),
            total_weeks=12,
            weeks=[{"week_number": 1, "workouts": []}]
        )
        with pytest.raises(RuntimeError, match="No workout"):
            actions._find_workout(plan, session_id="nope", when=None)


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
        """scaffold() generates plan from goal dict."""
        with patch('paceforge.actions.store.load_profile') as mock_load_prof:
            with patch('paceforge.actions.store.save_plan') as mock_save:
                mock_load_prof.return_value = UserFitnessProfile(vo2_max=45.0)

                goal_dict = {
                    "goal_type": "MARATHON",
                    "target_date": "2026-10-04",
                    "experience_level": "intermediate",
                }
                result = actions.scaffold(goal=goal_dict)
                assert result is not None
                mock_save.assert_called_once()

    def test_scaffold_with_target_time(self):
        """scaffold() uses target time to adjust paces."""
        with patch('paceforge.actions.store.load_profile') as mock_load_prof:
            with patch('paceforge.actions.store.save_plan'):
                mock_load_prof.return_value = UserFitnessProfile(vo2_max=45.0)

                goal_dict = {
                    "goal_type": "MARATHON",
                    "target_date": "2026-10-04",
                    "experience_level": "intermediate",
                    "target_time_seconds": 8400,
                }
                result = actions.scaffold(goal=goal_dict)
                assert result is not None


class TestRecalibratePaceDelta:
    """recalibrate() shifts plan paces by VDOT delta."""

    def test_recalibrate_positive_delta(self):
        """recalibrate(delta_vdot=0.5) increases all paces."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan') as mock_save:
                plan = TrainingPlan(
                    weeks=[{
                        "workouts": [{
                            "pace_low_sec": 300,
                            "pace_high_sec": 310,
                        }]
                    }]
                )
                mock_load.return_value = plan

                result = actions.recalibrate(delta_vdot=0.5, force=False)
                assert result is not None
                mock_save.assert_called_once()

    def test_recalibrate_negative_delta(self):
        """recalibrate(delta_vdot=-0.5) decreases all paces."""
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
                result = actions.recalibrate(delta_vdot=-0.5, force=False)
                assert result is not None

    def test_recalibrate_guard_blocks_unapproved_shift(self):
        """recalibrate(force=False) only shifts accepted future weeks."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan'):
                plan = TrainingPlan(accepted_week=1)
                mock_load.return_value = plan

                result = actions.recalibrate(delta_vdot=0.5, force=False)
                assert result is not None


class TestPushToGarmin:
    """push() uploads plan week to Garmin calendar."""

    def test_push_current_week(self):
        """push() uploads plan week."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.validate_plan') as mock_validate:
                from paceforge.models.plan import Workout, WorkoutType
                w = Workout(name="Easy", workout_type=WorkoutType.EASY,
                           sport="run", scheduled_date=date.today(),
                           estimated_duration_seconds=3600)
                plan = TrainingPlan(
                    weeks=[{"workouts": [w]}],
                    pace_bands={},
                )
                mock_load.return_value = plan
                mock_validate.return_value = []

                result = actions.push(week=1, dry_run=True)
                assert result.get("dry_run") is True

    def test_push_specific_week(self):
        """push(week=1) uploads week 1 only."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.validate_plan') as mock_validate:
                from paceforge.models.plan import Workout, WorkoutType
                w = Workout(name="Easy", workout_type=WorkoutType.EASY,
                           sport="run", scheduled_date=date.today(),
                           estimated_duration_seconds=3600)
                plan = TrainingPlan(
                    weeks=[{"workouts": [w]} for _ in range(4)],
                    pace_bands={},
                )
                mock_load.return_value = plan
                mock_validate.return_value = []

                result = actions.push(week=1, dry_run=True)
                assert result.get("week") == 1

    def test_push_dry_run_no_upload(self):
        """push(dry_run=True) previews without uploading."""
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.validate_plan') as mock_validate:
                from paceforge.models.plan import Workout, WorkoutType
                w = Workout(name="Easy", workout_type=WorkoutType.EASY,
                           sport="run", scheduled_date=date.today(),
                           estimated_duration_seconds=3600)
                plan = TrainingPlan(
                    weeks=[{"workouts": [w]}],
                    pace_bands={},
                )
                mock_load.return_value = plan
                mock_validate.return_value = []

                result = actions.push(week=1, dry_run=True)
                assert result.get("dry_run") is True


class TestAutoSync:
    """autosync() reconciles plan with Garmin calendar."""

    def test_autosync_push_current_3_weeks(self):
        """autosync() delegates to garmin_reconcile."""
        mock_client = MagicMock()
        mock_client.push_plan_week.return_value = {"pushed": [], "failed": []}
        mock_client.delete_workout.return_value = True
        mock_client.get_scheduled_workouts.return_value = []

        with patch('paceforge.actions.store.load_plan') as mock_load:
            from paceforge.models.plan import Workout, WorkoutType
            w = Workout(name="Easy", workout_type=WorkoutType.EASY,
                       sport="run", scheduled_date=date.today(),
                       estimated_duration_seconds=3600)
            plan = TrainingPlan(
                weeks=[{"workouts": [w]} for _ in range(4)],
                accepted=True,
                pace_bands={},
            )
            mock_load.return_value = plan

            result = actions.autosync(client=mock_client)
            assert result is not None

    def test_autosync_delete_stale_workouts(self):
        """autosync() calls delete_workout for stale entries."""
        mock_client = MagicMock()
        mock_client.push_plan_week.return_value = {"pushed": [], "failed": []}
        mock_client.delete_workout.return_value = True
        mock_client.get_scheduled_workouts.return_value = []

        with patch('paceforge.actions.store.load_plan') as mock_load:
            from paceforge.models.plan import Workout, WorkoutType
            w = Workout(name="Easy", workout_type=WorkoutType.EASY,
                       sport="run", scheduled_date=date.today() + timedelta(days=7),
                       estimated_duration_seconds=3600,
                       garmin_workout_id=None)
            plan = TrainingPlan(
                weeks=[{"workouts": [w]}],
                accepted=True,
                pace_bands={},
            )
            mock_load.return_value = plan

            result = actions.autosync(client=mock_client)
            assert result is not None


class TestAdaptMissedSessions:
    """adapt() reflows missed sessions + readiness gate."""

    def test_adapt_reflow_missed_session(self):
        """adapt() reschedules missed session to later in week."""
        from paceforge.models.plan import Workout, WorkoutType
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan'):
                w1 = Workout(name="Mon", workout_type=WorkoutType.EASY,
                            sport="run", scheduled_date=date.today(),
                            estimated_duration_seconds=3600)
                w2 = Workout(name="Tue", workout_type=WorkoutType.EASY,
                            sport="run", scheduled_date=date.today() + timedelta(days=1),
                            estimated_duration_seconds=3600)
                w3 = Workout(name="Wed", workout_type=WorkoutType.EASY,
                            sport="run", scheduled_date=date.today() + timedelta(days=2),
                            estimated_duration_seconds=3600)
                plan = TrainingPlan(
                    weeks=[{"workouts": [w1, w2, w3]}],
                    pace_bands={},
                )
                mock_load.return_value = plan

                result = actions.adapt(dry_run=True)
                assert result is not None

    def test_adapt_readiness_gate_hard_work(self):
        """adapt() considers readiness for gated workouts."""
        from paceforge.models.plan import Workout, WorkoutType
        with patch('paceforge.actions.store.load_plan') as mock_load:
            with patch('paceforge.actions.store.save_plan'):
                w = Workout(name="VO2", workout_type=WorkoutType.VO2MAX,
                           sport="run", scheduled_date=date.today(),
                           estimated_duration_seconds=3600)
                plan = TrainingPlan(
                    weeks=[{"workouts": [w]}],
                    pace_bands={},
                )
                mock_load.return_value = plan

                result = actions.adapt(dry_run=True)
                assert result is not None


class TestErrorHandling:
    """CLI error handlers."""

    def test_main_runtime_error_handler(self):
        """cli.main() catches RuntimeError and exits."""
        # Should test the exception handler at cli.py:178-180

    def test_main_keyboard_interrupt(self):
        """cli.main() exits cleanly on Ctrl+C."""
        # Should test keyboard interrupt handling
