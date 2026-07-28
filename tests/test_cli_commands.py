"""Test CLI command parsing and dispatch — currently 0% covered."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import Mock, patch, MagicMock

import pytest

from paceforge import cli


class TestCliMainCommandDispatch:
    """CLI argument parsing and command routing."""

    def test_login_command(self):
        """login subcommand invokes actions.login()."""
        with patch('paceforge.cli.actions.login') as mock_login:
            mock_login.return_value = "base64_token_xyz"
            result = cli.main(['login'])
            mock_login.assert_called_once()
            assert result == 0

    def test_sync_command_default_args(self):
        """sync subcommand with default lookback_days=90, details=40."""
        with patch('paceforge.cli.actions.sync') as mock_sync:
            mock_sync.return_value = {"activities": 10, "written": True}
            result = cli.main(['sync'])
            mock_sync.assert_called_once_with(lookback_days=90, details_limit=40)
            assert result == 0

    def test_sync_command_custom_lookback(self):
        """sync --lookback-days 180 passes to actions.sync()."""
        with patch('paceforge.cli.actions.sync') as mock_sync:
            cli.main(['sync', '--lookback-days', '180'])
            mock_sync.assert_called_once_with(lookback_days=180, details_limit=40)

    def test_sync_command_custom_details_limit(self):
        """sync --details 0 skips detail fetching."""
        with patch('paceforge.cli.actions.sync') as mock_sync:
            cli.main(['sync', '--details', '0'])
            mock_sync.assert_called_once_with(lookback_days=90, details_limit=0)

    def test_plan_command_required_arguments(self):
        """plan requires --goal and --date."""
        with patch('paceforge.cli.actions.scaffold'):
            # Missing --goal should error
            with pytest.raises(SystemExit):
                cli.main(['plan', '--date', '2026-10-04'])

    def test_plan_command_marathon_goal(self):
        """plan --goal MARATHON scaffolds marathon training."""
        with patch('paceforge.cli.actions.scaffold') as mock_scaffold:
            cli.main([
                'plan', '--goal', 'MARATHON', '--date', '2026-10-04',
                '--level', 'intermediate'
            ])
            args, kwargs = mock_scaffold.call_args
            plan_dict = args[0]
            assert plan_dict['goal_type'] == 'MARATHON'

    def test_plan_command_custom_training_days(self):
        """plan --days defines session schedule."""
        with patch('paceforge.cli.actions.scaffold') as mock_scaffold:
            cli.main([
                'plan', '--goal', '5K', '--date', '2026-10-04',
                '--days', 'monday,wednesday,friday'
            ])
            args, kwargs = mock_scaffold.call_args
            plan_dict = args[0]
            assert 'monday' in plan_dict['training_days']

    def test_status_command(self):
        """status outputs profile + plan summary."""
        with patch('paceforge.cli.actions.status') as mock_status:
            mock_status.return_value = {"vo2_max": 45, "current_plan": "marathon"}
            cli.main(['status'])
            mock_status.assert_called_once()

    def test_analyze_command(self):
        """analyze invokes analytics over stored profile."""
        with patch('paceforge.cli.actions.analyze') as mock_analyze:
            mock_analyze.return_value = {"analyses": 5}
            cli.main(['analyze'])
            mock_analyze.assert_called_once()

    def test_validate_command(self):
        """validate checks data/plan.json against rules."""
        with patch('paceforge.cli.actions.validate') as mock_validate:
            mock_validate.return_value = {"valid": True}
            cli.main(['validate'])
            mock_validate.assert_called_once()

    def test_plan_md_command(self):
        """plan-md regenerates plan.md deterministically."""
        with patch('paceforge.cli.actions.plan_md') as mock_plan_md:
            cli.main(['plan-md'])
            mock_plan_md.assert_called_once()

    def test_recalibrate_command_required_delta(self):
        """recalibrate requires --delta argument."""
        with pytest.raises(SystemExit):
            cli.main(['recalibrate'])

    def test_recalibrate_command_positive_delta(self):
        """recalibrate --delta 0.5 shifts paces +0.5 VDOT."""
        with patch('paceforge.cli.actions.recalibrate') as mock_recal:
            cli.main(['recalibrate', '--delta', '0.5'])
            args, kwargs = mock_recal.call_args
            assert args[0] == 0.5
            assert kwargs.get('force') is False

    def test_recalibrate_command_force_flag(self):
        """recalibrate --force bypasses accepted-plan guard."""
        with patch('paceforge.cli.actions.recalibrate') as mock_recal:
            cli.main(['recalibrate', '--delta', '-0.5', '--force'])
            args, kwargs = mock_recal.call_args
            assert kwargs['force'] is True

    def test_push_command_default_week(self):
        """push without --week pushes current + next 2."""
        with patch('paceforge.cli.actions.push') as mock_push:
            cli.main(['push'])
            args, kwargs = mock_push.call_args
            assert kwargs.get('week') is None
            assert kwargs.get('dry_run') is False

    def test_push_command_specific_week(self):
        """push --week 3 pushes week 3 only."""
        with patch('paceforge.cli.actions.push') as mock_push:
            cli.main(['push', '--week', '3'])
            args, kwargs = mock_push.call_args
            assert kwargs['week'] == 3

    def test_push_command_dry_run(self):
        """push --dry-run previews without uploading."""
        with patch('paceforge.cli.actions.push') as mock_push:
            cli.main(['push', '--dry-run'])
            args, kwargs = mock_push.call_args
            assert kwargs['dry_run'] is True

    def test_autosync_command(self):
        """autosync reconciles plan with Garmin calendar."""
        with patch('paceforge.cli.actions.autosync') as mock_autosync:
            cli.main(['autosync'])
            mock_autosync.assert_called_once()

    def test_adapt_command_dry_run(self):
        """adapt --dry-run previews reflow without writing."""
        with patch('paceforge.cli.actions.adapt') as mock_adapt:
            cli.main(['adapt', '--dry-run'])
            args, kwargs = mock_adapt.call_args
            assert kwargs['dry_run'] is True

    def test_garmin_delete_command(self):
        """garmin-delete removes all plan workouts from Garmin."""
        with patch('paceforge.cli.actions.garmin_delete') as mock_delete:
            cli.main(['garmin-delete'])
            mock_delete.assert_called_once()


class TestCliOutput:
    """Output formatting and serialization."""

    def test_emit_dict_as_json(self):
        """_emit() serializes dict to JSON."""
        obj = {"key": "value", "number": 42}
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli._emit(obj)
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed == obj

    def test_emit_list_as_json(self):
        """_emit() serializes list to JSON array."""
        obj = [1, 2, 3]
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli._emit(obj)
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed == obj

    def test_emit_string_as_json(self):
        """_emit() wraps string in quotes."""
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli._emit("hello")
            output = mock_stdout.getvalue()
            assert output.strip() == '"hello"'

    def test_emit_number_as_json(self):
        """_emit() serializes number literally."""
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli._emit(42)
            output = mock_stdout.getvalue()
            assert output.strip() == "42"
