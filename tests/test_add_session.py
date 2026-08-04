"""Schedule a class (e.g. HYROX) onto the plan as a real Workout."""
from datetime import date, datetime

from paceforge import actions, store
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout
from paceforge.models.profile import RecentActivity


def _plan_with_week(week_start: date):
    return TrainingPlan(
        name="t", goal_type="HALF_MARATHON", target_date=date(2026, 9, 20), total_weeks=1,
        weeks=[TrainingWeek(week_number=1, workouts=[
            Workout(name="Easy", workout_type="easy_run", scheduled_date=week_start,
                   estimated_distance_meters=6000),
        ])],
    )


def test_add_session_appends_workout_to_plan():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45, name="Hyrox Class")
    plan = store.load_plan()
    added = [w for w in plan.weeks[0].workouts if w.name == "Hyrox Class"]
    assert len(added) == 1 and added[0].workout_type == "hyrox_mixed"


def test_add_session_defaults_non_hyrox_sport_to_cross_training():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=45)
    plan = store.load_plan()
    added = plan.weeks[0].workouts[-1]
    assert added.workout_type == "cross_training" and added.name == "Cardio Class"


def test_add_session_matches_existing_garmin_activity_same_day():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    store.save_activities([RecentActivity(
        activity_id=1, name="Cardio", activity_type="indoor_cardio",
        start_time=datetime(2026, 8, 4, 7, 0), duration_seconds=2700, distance_meters=0,
    )])
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45)
    plan = store.load_plan()
    added = next(w for w in plan.weeks[0].workouts if w.session_id == result["session_ids"][0])
    assert added.matched_activity_ids == [1] and added.completed


def test_add_session_with_no_plan_creates_bare_container():
    """Scheduling a class must never require a periodized running plan to exist."""
    assert store.load_plan() is None
    actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45, name="Hyrox Class")
    plan = store.load_plan()
    assert plan is not None and plan.accepted
    added = [w for w in plan.weeks[0].workouts if w.name == "Hyrox Class"]
    assert len(added) == 1


def test_add_session_repeat_weekly_schedules_each_week():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45,
                                 repeat_weeks=3)
    plan = store.load_plan()
    dates = sorted(w.scheduled_date for w in plan.weeks[0].workouts if w.name == "Hyrox Class")
    assert dates == [date(2026, 8, 4), date(2026, 8, 11), date(2026, 8, 18)]
    assert len(result["session_ids"]) == 3


def test_add_session_repeat_weeks_clamped_to_max():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45,
                                 repeat_weeks=999)
    assert result["repeat_weeks"] == 52


def test_absurd_duration_is_clamped_to_a_plausible_class_length():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=99999, name="Long")
    added = next(w for w in store.load_plan().weeks[0].workouts if w.name == "Long")
    assert added.estimated_duration_seconds == 480 * 60


def test_negative_duration_does_not_reach_the_plan():
    store.save_plan(_plan_with_week(date(2026, 8, 1)))
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=-30, name="Negative")
    added = next(w for w in store.load_plan().weeks[0].workouts if w.name == "Negative")
    assert added.estimated_duration_seconds == 5 * 60
