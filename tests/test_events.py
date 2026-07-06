"""Tests for per-event training-structure profiles."""

from __future__ import annotations

import pytest

from paceforge.engine.events import event_profile
from paceforge.models.plan import WorkoutType
from paceforge.models.profile import GoalType


def test_hyrox_profile_has_compromised_bias():
    assert event_profile(GoalType.HYROX).compromised_bias is True


def test_road_5k_profile_has_no_compromised_bias():
    assert event_profile(GoalType.FIVE_K).compromised_bias is False


@pytest.mark.parametrize("goal", list(GoalType))
def test_every_profile_phase_ratios_are_named_and_sum_to_one(goal):
    prof = event_profile(goal)
    assert set(prof.phase_weeks_ratio) == {"base", "build", "peak", "taper"}
    assert abs(sum(prof.phase_weeks_ratio.values()) - 1.0) < 0.01


@pytest.mark.parametrize("goal", list(GoalType))
def test_quality_emphasis_is_running_types(goal):
    prof = event_profile(goal)
    assert prof.quality_emphasis
    non_running = {WorkoutType.HYROX_MIXED, WorkoutType.CROSS_TRAINING, WorkoutType.REST}
    assert not (set(prof.quality_emphasis) & non_running)
