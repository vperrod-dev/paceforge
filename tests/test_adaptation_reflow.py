"""Missed-session reflow + readiness gating."""
from datetime import date

from paceforge.engine.adaptation import readiness_gate, reflow_missed_sessions
from paceforge.models.plan import TrainingPlan, TrainingWeek, Workout, WorkoutType

TODAY = date(2026, 7, 3)  # Friday of the test week


def _wo(day, wtype, name, completed=False, km=8.0):
    return Workout(
        name=name, workout_type=wtype, scheduled_date=date(2026, 6, 29) if day == 0
        else date(2026, 6, 29 + day) if day < 2 else date(2026, 7, day - 1),
        estimated_distance_meters=km * 1000, completed=completed,
    )


def _plan(workouts):
    return TrainingPlan(name="p", goal_type="HYROX", target_date=date(2026, 10, 1),
                        total_weeks=1,
                        weeks=[TrainingWeek(week_number=1, workouts=workouts)])


def test_missed_quality_moves_to_future_easy_slot():
    missed = _wo(0, WorkoutType.TEMPO, "Tempo")               # Mon, missed
    easy = _wo(6, WorkoutType.EASY_RUN, "Easy")               # Sun, future
    plan = _plan([missed, easy])
    changes = reflow_missed_sessions(plan, today=TODAY)
    assert len(changes) == 1 and "Moved" in changes[0]
    assert missed.scheduled_date == date(2026, 7, 5)
    assert len(plan.weeks[0].workouts) == 1  # easy run gave way


def test_missed_quality_never_lands_next_to_hard_day():
    missed = _wo(0, WorkoutType.TEMPO, "Tempo")                        # Mon, missed
    hard = _wo(5, WorkoutType.VO2MAX, "VO2", completed=True)           # Sat
    easy = _wo(6, WorkoutType.EASY_RUN, "Easy")                        # Sun (adjacent to Sat)
    plan = _plan([missed, hard, easy])
    changes = reflow_missed_sessions(plan, today=TODAY)
    assert len(changes) == 1 and "Dropped" in changes[0]
    assert "dropped" in missed.notes.lower()


def test_completed_sessions_not_reflowed():
    done = _wo(0, WorkoutType.TEMPO, "Tempo", completed=True)
    easy = _wo(6, WorkoutType.EASY_RUN, "Easy")
    plan = _plan([done, easy])
    assert reflow_missed_sessions(plan, today=TODAY) == []


def test_readiness_gate_downgrades_imminent_quality():
    quality = _wo(5, WorkoutType.HYROX_MIXED, "Brick")  # Sat = today+1
    plan = _plan([quality])
    changes = readiness_gate(plan, {"score": 18, "band": "low"}, today=TODAY)
    assert len(changes) == 1
    downgraded = plan.weeks[0].workouts[0]
    assert downgraded.workout_type == WorkoutType.EASY_RUN
    assert "was: Brick" in downgraded.name


def test_high_rpe_yesterday_gates_even_when_readiness_ok():
    quality = _wo(5, WorkoutType.TEMPO, "Tempo")
    plan = _plan([quality])
    changes = readiness_gate(plan, {"score": 70, "band": "moderate"},
                             yesterday_rpe=9, today=TODAY)
    assert len(changes) == 1 and "RPE 9" in changes[0]


def test_no_gate_when_ready():
    quality = _wo(5, WorkoutType.TEMPO, "Tempo")
    plan = _plan([quality])
    assert readiness_gate(plan, {"score": 80, "band": "high"},
                          yesterday_rpe=6, today=TODAY) == []
