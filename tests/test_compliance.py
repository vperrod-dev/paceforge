"""Plan-vs-actual compliance bands + weekly rollup."""
from datetime import date

from paceforge.engine.compliance import annotate_plan, weekly_compliance
from paceforge.models.calendar import ScheduledItem
from paceforge.models.plan import (
    TrainingPlan,
    TrainingWeek,
    Workout,
    WorkoutType,
)
from paceforge.models.profile import RecentActivity

TODAY = date(2026, 7, 3)


def _activity(activity_id, day, km=10.0, minutes=50, atype="running"):
    return RecentActivity(
        activity_id=activity_id, name="sess", activity_type=atype,
        start_time=f"2026-07-{day:02d}T07:00:00",
        distance_meters=km * 1000, duration_seconds=minutes * 60,
    )


def _workout(day, wtype=WorkoutType.EASY_RUN, km=10.0, minutes=None, matched=None):
    return Workout(
        name="w", workout_type=wtype, scheduled_date=date(2026, 7, day),
        estimated_distance_meters=km * 1000 if km else None,
        estimated_duration_seconds=minutes * 60 if minutes else None,
        matched_activity_ids=matched or [], completed=bool(matched),
    )


def _plan(workouts):
    return TrainingPlan(
        name="p", goal_type="HYROX", target_date=date(2026, 10, 1),
        total_weeks=1, weeks=[TrainingWeek(week_number=1, workouts=workouts)],
    )


def test_run_on_plan_is_green():
    plan = _plan([_workout(1, km=10.0, matched=[11])])
    annotate_plan(plan, [_activity(11, 1, km=10.5)], today=TODAY)
    cm = plan.weeks[0].workouts[0].completion_metrics
    assert cm["status"] == "green" and cm["ratio"] == 1.05


def test_half_distance_run_is_yellow():
    plan = _plan([_workout(1, km=10.0, matched=[11])])
    annotate_plan(plan, [_activity(11, 1, km=6.0)], today=TODAY)
    assert plan.weeks[0].workouts[0].completion_metrics["status"] == "yellow"


def test_way_off_is_orange():
    plan = _plan([_workout(1, km=10.0, matched=[11])])
    annotate_plan(plan, [_activity(11, 1, km=3.0)], today=TODAY)
    assert plan.weeks[0].workouts[0].completion_metrics["status"] == "orange"


def test_missed_past_workout_is_red():
    plan = _plan([_workout(1)])
    annotate_plan(plan, [], today=TODAY)
    assert plan.weeks[0].workouts[0].completion_metrics["status"] == "red"


def test_future_workout_is_pending():
    plan = _plan([_workout(5)])
    annotate_plan(plan, [], today=TODAY)
    assert plan.weeks[0].workouts[0].completion_metrics is None


def test_hyrox_mixed_graded_on_duration_not_distance():
    # 60-min HYROX session planned; did 58 min but only 4 km of "distance".
    plan = _plan([_workout(1, wtype=WorkoutType.HYROX_MIXED, km=8.0, minutes=60,
                           matched=[11])])
    annotate_plan(plan, [_activity(11, 1, km=4.0, minutes=58, atype="hiit")], today=TODAY)
    cm = plan.weeks[0].workouts[0].completion_metrics
    assert cm["status"] == "green" and cm["ratio"] == round(58 / 60, 2)


def test_weekly_rollup_counts_and_unplanned():
    plan = _plan([
        _workout(1, km=10.0, matched=[11]),   # green
        _workout(2),                          # red (missed)
        _workout(5),                          # pending (future)
    ])
    acts = [_activity(11, 1, km=10.0), _activity(99, 2, atype="strength_training")]
    annotate_plan(plan, acts, today=TODAY)
    roll = weekly_compliance(plan, acts, today=TODAY)
    wk = roll["weeks"][0]
    assert wk["counts"]["green"] == 1 and wk["counts"]["red"] == 1 and wk["counts"]["pending"] == 1
    assert wk["compliance_pct"] == 50
    assert [u["activity_id"] for u in wk["unplanned"]] == [99]
    assert roll["overall_pct"] == 50


def test_future_week_not_scored():
    plan = TrainingPlan(
        name="p", goal_type="HYROX", target_date=date(2026, 10, 1), total_weeks=2,
        weeks=[
            TrainingWeek(week_number=1, workouts=[_workout(1, matched=[11])]),
            TrainingWeek(week_number=2, workouts=[_workout(20)]),
        ],
    )
    acts = [_activity(11, 1)]
    annotate_plan(plan, acts, today=TODAY)
    roll = weekly_compliance(plan, acts, today=TODAY)
    assert len(roll["weeks"]) == 1 and roll["overall_pct"] == 100


def _item(day, completed=False, matched=None, sport="Cardio"):
    return ScheduledItem(date=date(2026, 7, day), sport=sport, title="Un1t",
                         duration_min=45, completed=completed,
                         matched_activity_ids=matched or [])


def test_completed_class_is_a_planned_session_not_unplanned():
    plan = _plan([_workout(1, matched=[11]), _workout(5)])
    acts = [_activity(11, 1), _activity(99, 2, atype="indoor_cardio")]
    annotate_plan(plan, acts, today=TODAY)
    wk = weekly_compliance(plan, acts, today=TODAY, items=[_item(2, True, ["99"])])["weeks"][0]
    assert wk["unplanned"] == []


def test_completed_class_scores_green():
    plan = _plan([_workout(1, matched=[11]), _workout(5)])
    acts = [_activity(11, 1), _activity(99, 2, atype="indoor_cardio")]
    annotate_plan(plan, acts, today=TODAY)
    wk = weekly_compliance(plan, acts, today=TODAY, items=[_item(2, True, ["99"])])["weeks"][0]
    assert wk["counts"]["green"] == 2


def test_skipped_class_in_the_past_scores_red():
    plan = _plan([_workout(1, matched=[11]), _workout(5)])
    acts = [_activity(11, 1)]
    annotate_plan(plan, acts, today=TODAY)
    wk = weekly_compliance(plan, acts, today=TODAY, items=[_item(2)])["weeks"][0]
    assert wk["counts"]["red"] == 1
