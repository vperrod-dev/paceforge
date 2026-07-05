"""Match Garmin activities to scheduled plan workouts."""
from datetime import date, datetime

from paceforge.engine.matching import match_plan_to_activities
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout
from paceforge.models.profile import RecentActivity


def _act(aid, day, dist, atype="running"):
    return RecentActivity(activity_id=aid, name="run", activity_type=atype,
                          start_time=datetime(day.year, day.month, day.day, 7, 0),
                          distance_meters=dist, duration_seconds=dist / 3)


def _plan(*workouts):
    return TrainingPlan(name="t", goal_type="HYROX", target_date=date(2026, 11, 13),
                        total_weeks=1,
                        weeks=[TrainingWeek(week_number=1, workouts=list(workouts))])


def test_matches_run_on_same_date():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                         estimated_distance_meters=6000))
    changed = match_plan_to_activities(plan, [_act(1, d, 6000)])
    wo = plan.weeks[0].workouts[0]
    assert changed == 1 and wo.matched_activity_ids == [1] and wo.completed


def test_rest_days_never_match():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="rest", name="Rest", scheduled_date=d))
    match_plan_to_activities(plan, [_act(1, d, 5000)])
    assert plan.weeks[0].workouts[0].matched_activity_ids == []


def test_strength_activity_does_not_match_run():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                         estimated_distance_meters=6000))
    match_plan_to_activities(plan, [_act(1, d, 0, atype="strength_training")])
    assert plan.weeks[0].workouts[0].matched_activity_ids == []


def test_nearest_distance_wins_when_two_runs():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="long_run", name="Long", scheduled_date=d,
                         estimated_distance_meters=15000))
    match_plan_to_activities(plan, [_act(1, d, 6000), _act(2, d, 14500)])
    assert plan.weeks[0].workouts[0].matched_activity_ids == [2]


def test_one_activity_not_shared_by_two_workouts():
    d = date(2026, 6, 1)
    plan = _plan(
        Workout(workout_type="easy_run", name="A", scheduled_date=d, estimated_distance_meters=6000),
        Workout(workout_type="tempo", name="B", scheduled_date=d, estimated_distance_meters=6000),
    )
    match_plan_to_activities(plan, [_act(1, d, 6000)])
    matched = [w.matched_activity_ids for w in plan.weeks[0].workouts]
    assert sorted(matched) == [[], [1]]


def test_no_activity_means_no_match():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                         estimated_distance_meters=6000))
    assert match_plan_to_activities(plan, []) == 0


def test_activity_one_day_off_still_matches():
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=date(2026, 6, 1),
                         estimated_distance_meters=6000))
    match_plan_to_activities(plan, [_act(1, date(2026, 6, 2), 6000)])
    assert plan.weeks[0].workouts[0].matched_activity_ids == [1]


def test_activity_two_days_off_does_not_match():
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=date(2026, 6, 1),
                         estimated_distance_meters=6000))
    match_plan_to_activities(plan, [_act(1, date(2026, 6, 3), 6000)])
    assert plan.weeks[0].workouts[0].matched_activity_ids == []


def test_strength_matches_cross_training_slot():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="cross_training", name="Stations", scheduled_date=d,
                         estimated_duration_seconds=3600))
    changed = match_plan_to_activities(
        plan, [_act(1, d, 0, atype="strength_training")])
    wo = plan.weeks[0].workouts[0]
    assert changed == 1 and wo.matched_activity_ids == [1] and wo.completed


def test_hiit_matches_hyrox_mixed_by_duration():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="hyrox_mixed", name="Sim", scheduled_date=d,
                         estimated_duration_seconds=3600))
    short = _act(1, d, 2000, atype="hiit")   # ~11 min
    long = _act(2, d, 11000, atype="hiit")   # ~61 min — nearest duration wins
    match_plan_to_activities(plan, [short, long])
    assert plan.weeks[0].workouts[0].matched_activity_ids == [2]


def test_run_slot_claims_run_before_hyrox_slot():
    d = date(2026, 6, 1)
    run_slot = Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                       estimated_distance_meters=6000)
    hyrox_slot = Workout(workout_type="hyrox_mixed", name="Sim", scheduled_date=d,
                         estimated_duration_seconds=2000)
    plan = _plan(run_slot, hyrox_slot)
    match_plan_to_activities(plan, [_act(1, d, 6000)])
    assert run_slot.matched_activity_ids == [1]
    assert hyrox_slot.matched_activity_ids == []


def test_rpe_copied_onto_matched_workout():
    d = date(2026, 6, 1)
    plan = _plan(Workout(workout_type="easy_run", name="Easy", scheduled_date=d,
                         estimated_distance_meters=6000))
    match_plan_to_activities(plan, [_act(1, d, 6000)],
                             rpe_map={1: {"rpe": 7}})
    assert plan.weeks[0].workouts[0].user_rpe == 7
