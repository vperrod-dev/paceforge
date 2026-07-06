"""HYROX workout builders + HYROX-aware planning."""
from datetime import date, timedelta

from paceforge.engine.planner import generate_plan
from paceforge.engine.validate import validate_plan
from paceforge.engine.vdot import paces_from_vdot
from paceforge.engine.workouts import WorkoutFactory
from paceforge.models.plan import WorkoutType
from paceforge.models.profile import TrainingGoal, UserFitnessProfile


def _factory():
    return WorkoutFactory(paces_from_vdot(50))


def test_compromised_brick_structure():
    w = _factory().hyrox_compromised_brick(reps=6, stations=["Sled_Pull_50m"])
    assert w.workout_type == WorkoutType.HYROX_MIXED
    repeat = next(s for s in w.steps if s.repeat_count)
    assert repeat.repeat_count == 6
    station, run = repeat.steps
    assert "Sled Pull" in station.description
    assert run.distance_meters == 1000 and run.target_low is not None
    assert w.estimated_distance_meters == 10000  # 6 x 1km + 4km warm/cool


def test_race_simulation_alternates_runs_and_stations():
    w = _factory().hyrox_race_simulation(segments=4)
    assert w.workout_type == WorkoutType.HYROX_MIXED
    kinds = [("run" if s.distance_meters == 1000 else "station")
             for s in w.steps[1:-1]]  # strip warmup/cooldown
    assert kinds == ["run", "station"] * 4


def test_station_day_targets_focus_stations():
    w = _factory().station_day(focus_stations=["Sled_Pull_50m", "Wall_Balls"], sets=4)
    assert w.workout_type == WorkoutType.CROSS_TRAINING
    assert "Sled Pull" in w.name and "Wall Balls" in w.name
    blocks = [s for s in w.steps if s.repeat_count]
    assert len(blocks) == 2 and all(b.repeat_count == 4 for b in blocks)
    assert w.estimated_duration_seconds and w.estimated_duration_seconds > 1500


def test_hyrox_plan_is_running_only_and_validates():
    profile = UserFitnessProfile(vo2_max=52.0, resting_hr=50, max_hr=190)
    goal = TrainingGoal(
        goal_type="HYROX",
        target_date=date.today() + timedelta(weeks=10),
        experience_level="intermediate",
        training_days=["tuesday", "thursday", "saturday", "sunday"],
        long_run_day="sunday",
    )
    plan = generate_plan(profile, goal)
    types = {str(wo.workout_type) for wk in plan.weeks for wo in wk.workouts}
    assert "hyrox_mixed" not in types, "running-only plan must not schedule brick/sim"
    assert "cross_training" not in types, "running-only plan must not schedule a station day"
    # Compromised 1km repeats (race-pace intervals) replace the hybrid work.
    assert "race_pace" in types, "HYROX plan should bias to compromised 1km repeats"
    assert validate_plan(plan) == []


def test_marathon_plan_unaffected_by_hyrox_pools():
    profile = UserFitnessProfile(vo2_max=52.0, resting_hr=50, max_hr=190)
    goal = TrainingGoal(
        goal_type="MARATHON",
        target_date=date.today() + timedelta(weeks=12),
        experience_level="intermediate",
        training_days=["tuesday", "thursday", "saturday", "sunday"],
        long_run_day="sunday",
    )
    plan = generate_plan(profile, goal)
    types = {str(wo.workout_type) for wk in plan.weeks for wo in wk.workouts}
    assert "hyrox_mixed" not in types and "cross_training" not in types
    assert validate_plan(plan) == []
