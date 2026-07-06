"""Per-event training-structure profiles.

Maps a race/event type (``GoalType``) to the structural knobs the running-only
planner needs: how the weeks split across phases, which quality sessions to
emphasise, how big the long run may get, and whether to bias toward
compromised (run-under-fatigue) work. Paces stay in the VDOT engine — this
module only shapes *structure*.
"""

from __future__ import annotations

from dataclasses import dataclass

from paceforge.models.plan import WorkoutType
from paceforge.models.profile import GoalType


@dataclass(frozen=True)
class EventProfile:
    phase_weeks_ratio: dict[str, float]  # base/build/peak/taper — sums to 1.0
    quality_emphasis: list[WorkoutType]  # running quality types this event rewards
    long_run_cap_frac: float             # long run ≤ this fraction of weekly volume
    compromised_bias: bool               # inject run-under-fatigue sessions (HYROX)
    peak_km_factor: float                # peak weekly km ≈ athlete mileage × this


# Shorter, sharper events tilt toward VO2max/speed; longer events toward
# threshold/marathon-pace endurance. HYROX is a threshold + compromised-run event.
_PROFILES: dict[GoalType, EventProfile] = {
    GoalType.FIVE_K: EventProfile(
        phase_weeks_ratio={"base": 0.35, "build": 0.35, "peak": 0.20, "taper": 0.10},
        quality_emphasis=[WorkoutType.VO2MAX, WorkoutType.SPEED, WorkoutType.THRESHOLD],
        long_run_cap_frac=0.30,
        compromised_bias=False,
        peak_km_factor=1.0,
    ),
    GoalType.TEN_K: EventProfile(
        phase_weeks_ratio={"base": 0.35, "build": 0.35, "peak": 0.20, "taper": 0.10},
        quality_emphasis=[WorkoutType.THRESHOLD, WorkoutType.VO2MAX, WorkoutType.RACE_PACE],
        long_run_cap_frac=0.30,
        compromised_bias=False,
        peak_km_factor=1.05,
    ),
    GoalType.HALF_MARATHON: EventProfile(
        phase_weeks_ratio={"base": 0.40, "build": 0.35, "peak": 0.15, "taper": 0.10},
        quality_emphasis=[WorkoutType.THRESHOLD, WorkoutType.TEMPO, WorkoutType.RACE_PACE],
        long_run_cap_frac=0.30,
        compromised_bias=False,
        peak_km_factor=1.1,
    ),
    GoalType.MARATHON: EventProfile(
        phase_weeks_ratio={"base": 0.40, "build": 0.35, "peak": 0.15, "taper": 0.10},
        quality_emphasis=[WorkoutType.THRESHOLD, WorkoutType.RACE_PACE, WorkoutType.TEMPO],
        long_run_cap_frac=0.30,
        compromised_bias=False,
        peak_km_factor=1.15,
    ),
    GoalType.HYROX: EventProfile(
        phase_weeks_ratio={"base": 0.35, "build": 0.40, "peak": 0.15, "taper": 0.10},
        quality_emphasis=[WorkoutType.THRESHOLD, WorkoutType.RACE_PACE, WorkoutType.VO2MAX],
        long_run_cap_frac=0.28,
        compromised_bias=True,
        peak_km_factor=1.0,
    ),
    GoalType.CUSTOM: EventProfile(
        phase_weeks_ratio={"base": 0.40, "build": 0.35, "peak": 0.15, "taper": 0.10},
        quality_emphasis=[WorkoutType.THRESHOLD, WorkoutType.TEMPO, WorkoutType.VO2MAX],
        long_run_cap_frac=0.30,
        compromised_bias=False,
        peak_km_factor=1.05,
    ),
}


def event_profile(goal_type: GoalType) -> EventProfile:
    """Return the structural profile for an event type (CUSTOM as the fallback)."""
    return _PROFILES.get(goal_type, _PROFILES[GoalType.CUSTOM])
