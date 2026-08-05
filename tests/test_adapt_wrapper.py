"""e2e tests for the Actions.adapt() CLI wrapper.

Validates wrapper wiring at `actions.adapt` by providing deterministic
stubs for the engine helpers it delegates to: `reflow_missed_sessions`,
`readiness_gate`, and `compute_load_recovery`. We therefore validate control
flow and the resulting payload rather than engine behavior itself.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest

# Optional Garmin dependency is not installed in this environment; keep imports
# of the PaceForge package tree working by injecting harmless stubs.

_garmin = types.ModuleType("garminconnect")
_garmin.Garmin = type("Garmin", (), {})
_sys_mod = types.ModuleType("garminconnect.workout")
for _name in [
    "ConditionType",
    "ExecutableStep",
    "RunningWorkout",
    "StepType",
    "TargetType",
    "WorkoutSegment",
    "create_repeat_group",
]:
    setattr(_sys_mod, _name, type(_name, (), {}))
_garmin.workout = _sys_mod
sys.modules["garminconnect"] = _garmin
sys.modules["garminconnect.workout"] = _sys_mod
sys.modules["garminconnect_aio"] = types.ModuleType("garminconnect_aio")

from paceforge import actions, cli  # noqa: E402
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType  # noqa: E402


TODAY = date.today()


def _plan(workouts):
    return TrainingPlan(name="Test", goal_type="MARATHON",
                        target_date=date(2026, 10, 4), total_weeks=1,
                        weeks=[TrainingWeek(week_number=1, workouts=workouts)])


class TestAdaptWrapperSuccess:
    """adapt() happy path: wrapper composes engine + save/emit correctly."""

    def test_adapt_dry_run_returns_contract(self):
        w = Workout(name="Rest", workout_type=WorkoutType.EASY_RUN,
                    sport="run", scheduled_date=TODAY,
                    estimated_duration_seconds=3600)

        with patch('paceforge.actions.store.load_plan') as mock_load_plan:
            with patch('paceforge.actions.store.load_profile') as mock_load_prof:
                with patch('paceforge.actions.store.load_activities'):
                    with patch('paceforge.actions.store.load_history', return_value=[]):
                        with patch('paceforge.actions.store.rpe_by_activity'):
                            with patch('paceforge.actions.store.load_rpe', return_value={"entries": []}):
                                with patch('paceforge.actions.store.load_bike_rides'):
                                    with patch('paceforge.actions.validate_plan', return_value=[]):
                                        with patch('paceforge.actions.store.save_plan') as mock_save:
                                            plan = _plan([w])
                                            profile = type("P", (), {"vo2_max": 45})()
                                            mock_load_plan.return_value = plan
                                            mock_load_prof.return_value = profile

                                            with patch('paceforge.engine.load.compute_load_recovery',
                                                       return_value={"readiness_composite": {"score": 70, "band": "moderate"},
                                                                     "readiness": {"score": 70, "band": "moderate"}}):
                                                with patch('paceforge.engine.adaptation.reflow_missed_sessions',
                                                           return_value=["mk"]) as mock_reflow:
                                                    with patch('paceforge.engine.adaptation.readiness_gate',
                                                               return_value=["rd"]) as mock_gate:
                                                        result = actions.adapt(dry_run=True)

                                                        assert result["dry_run"] is True
                                                        assert result["changes"] == ["mk", "rd"]
                                                        mock_save.assert_not_called()
                                                        assert result["saved"] is False
                                                        assert result["readiness"]["score"] == 70
                                                        assert result["readiness"]["band"] == "moderate"
                                                        assert mock_reflow.call_count == 1
                                                        assert mock_gate.call_count == 1

    def test_adapt_no_dry_run_saves_when_changes_present(self):
        w = Workout(name="Easy", workout_type=WorkoutType.EASY_RUN,
                    sport="run", scheduled_date=TODAY,
                    estimated_duration_seconds=3600)

        with patch('paceforge.actions.store.load_plan') as mock_load_plan:
            with patch('paceforge.actions.store.load_profile') as mock_load_prof:
                with patch('paceforge.actions.store.load_activities'):
                    with patch('paceforge.actions.store.load_history', return_value=[]):
                        with patch('paceforge.actions.store.rpe_by_activity'):
                            with patch('paceforge.actions.store.load_rpe', return_value={"entries": []}):
                                with patch('paceforge.actions.store.load_bike_rides'):
                                    with patch('paceforge.actions.validate_plan', return_value=[]):
                                        plan = _plan([w])
                                        profile = type("P", (), {"vo2_max": 45})()
                                        mock_load_plan.return_value = plan
                                        mock_load_prof.return_value = profile

                                        with patch('paceforge.engine.load.compute_load_recovery',
                                                   return_value={"readiness_composite": {"score": 88, "band": "high"},
                                                                 "readiness": {"score": 88, "band": "high"}}):
                                            with patch('paceforge.engine.adaptation.reflow_missed_sessions',
                                                       return_value=["reflowed"]):
                                                with patch('paceforge.engine.adaptation.readiness_gate',
                                                           return_value=["gated"]):
                                                    with patch('paceforge.actions.store.save_plan') as mock_save:
                                                        result = actions.adapt(dry_run=False)

                                                        assert result["saved"] is True
                                                        mock_save.assert_called_once_with(plan)
                                                        assert result["changes"] == ["reflowed", "gated"]
                                                        assert result["readiness"]["score"] == 88

    def test_adapt_no_save_when_no_changes(self):
        w = Workout(name="Rest", workout_type=WorkoutType.EASY_RUN,
                    sport="run", scheduled_date=TODAY,
                    estimated_duration_seconds=3600)

        with patch('paceforge.actions.store.load_plan') as mock_load_plan:
            with patch('paceforge.actions.store.load_profile') as mock_load_prof:
                with patch('paceforge.actions.store.load_activities'):
                    with patch('paceforge.actions.store.load_history', return_value=[]):
                        with patch('paceforge.actions.store.rpe_by_activity'):
                            with patch('paceforge.actions.store.load_rpe', return_value={"entries": []}):
                                with patch('paceforge.actions.store.load_bike_rides'):
                                    with patch('paceforge.actions.validate_plan', return_value=[]):
                                        plan = _plan([w])
                                        profile = type("P", (), {"vo2_max": 45})()
                                        mock_load_plan.return_value = plan
                                        mock_load_prof.return_value = profile

                                        with patch('paceforge.engine.load.compute_load_recovery',
                                                   return_value={"readiness_composite": {"score": 88, "band": "high"},
                                                                 "readiness": {}}):
                                            with patch('paceforge.engine.adaptation.reflow_missed_sessions',
                                                       return_value=[]):
                                                with patch('paceforge.engine.adaptation.readiness_gate',
                                                           return_value=[]):
                                                    with patch('paceforge.actions.store.save_plan') as mock_save:
                                                        result = actions.adapt(dry_run=False)

                                                        assert result["changes"] == []
                                                        assert result["saved"] is False
                                                        mock_save.assert_not_called()


class TestAdaptWrapperErrorPaths:
    """adapt() wrapper guard conditions and failure surfacing."""

    def test_adapt_raises_when_no_plan(self):
        with patch('paceforge.actions.store.load_plan', return_value=None):
            with patch('paceforge.actions.store.load_profile', return_value=type("P", (), {"vo2_max": 45})()):
                with pytest.raises(RuntimeError, match="No plan at data/plan.json"):
                    actions.adapt(dry_run=False)

    def test_adapt_raises_when_no_profile(self):
        with patch('paceforge.actions.store.load_plan', return_value=_plan([])):
            with patch('paceforge.actions.store.load_profile', return_value=None):
                with pytest.raises(RuntimeError, match="No profile"):
                    actions.adapt(dry_run=False)

    def test_adapt_does_not_save_when_validation_issues_present(self):
        w = Workout(name="Bad", workout_type=WorkoutType.EASY_RUN,
                    sport="run", scheduled_date=TODAY,
                    estimated_duration_seconds=3600)
        plan = _plan([w])

        with patch('paceforge.actions.store.load_plan', return_value=plan):
            with patch('paceforge.actions.store.load_profile', return_value=type("P", (), {"vo2_max": 45})()):
                with patch('paceforge.actions.store.load_activities'):
                    with patch('paceforge.actions.store.load_history', return_value=[]):
                        with patch('paceforge.actions.store.rpe_by_activity'):
                            with patch('paceforge.actions.store.load_rpe', return_value={"entries": []}):
                                with patch('paceforge.actions.store.load_bike_rides'):
                                    with patch('paceforge.engine.load.compute_load_recovery',
                                               return_value={"readiness_composite": {"score": 88, "band": "high"},
                                                             "readiness": {}}):
                                        with patch('paceforge.engine.adaptation.reflow_missed_sessions',
                                                   return_value=["change1"]):
                                            with patch('paceforge.engine.adaptation.readiness_gate',
                                                       return_value=["change2"]):
                                                with patch('paceforge.actions.validate_plan',
                                                           return_value=["issue A", "issue B"]):
                                                    with patch('paceforge.actions.store.save_plan') as mock_save:
                                                        result = actions.adapt(dry_run=False)

                                                        assert result["validation_issues"] == ["issue A", "issue B"]
                                                        assert result["saved"] is False
                                                        mock_save.assert_not_called()

    def test_adapt_propagates_reflow_engine_exception(self):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("history truncated")

        with patch('paceforge.actions.store.load_plan', return_value=_plan([])):
            with patch('paceforge.actions.store.load_profile', return_value=type("P", (), {"vo2_max": 45})()):
                with patch('paceforge.actions.store.load_activities'):
                    with patch('paceforge.actions.store.load_history', return_value=[]):
                        with patch('paceforge.actions.store.rpe_by_activity'):
                            with patch('paceforge.actions.store.load_rpe', return_value={"entries": []}):
                                with patch('paceforge.actions.store.load_bike_rides'):
                                    with patch('paceforge.engine.load.compute_load_recovery', side_effect=_boom):
                                        with patch('paceforge.engine.adaptation.reflow_missed_sessions',
                                                   return_value=[]):
                                            with patch('paceforge.engine.adaptation.readiness_gate',
                                                       return_value=[]):
                                                with pytest.raises(RuntimeError, match="history truncated"):
                                                    actions.adapt(dry_run=False)


class TestAdaptCLIDispatch:
    """CLI layer to actions.adapt wiring."""

    def test_cli_adapt_dry_run_exits_zero(self):
        with patch('paceforge.cli.actions.adapt', return_value={"ok": True}) as mock_adapt:
            mock_stdout = StringIO()
            with patch('sys.stdout', mock_stdout):
                rc = cli.main(['adapt', '--dry-run'])
            assert rc == 0
            mock_adapt.assert_called_once_with(dry_run=True)
            out = mock_stdout.getvalue()
            assert "ok" in out
