"""Tests for the plan generator."""

from datetime import date, timedelta

from paceforge.engine.planner import _DAY_OFFSETS, _starting_and_peak_km, generate_plan
from paceforge.models.plan import WorkoutType
from paceforge.models.profile import (
    ExperienceLevel,
    GoalType,
    TrainingGoal,
    UserFitnessProfile,
)


def _make_profile(vo2_max: float = 45.0) -> UserFitnessProfile:
    return UserFitnessProfile(
        vo2_max=vo2_max,
        resting_hr=55,
        max_hr=185,
        weekly_mileage_km=35,
    )


def _make_goal(
    goal_type: GoalType = GoalType.HALF_MARATHON,
    weeks_out: int = 14,
    training_days: list[str] | None = None,
    long_run_day: str = "sunday",
) -> TrainingGoal:
    return TrainingGoal(
        goal_type=goal_type,
        target_date=date.today() + timedelta(weeks=weeks_out),
        experience_level=ExperienceLevel.INTERMEDIATE,
        training_days=training_days or ["tuesday", "wednesday", "thursday", "saturday", "sunday"],
        long_run_day=long_run_day,
    )


def test_quality_session_progresses_within_phase():
    from paceforge.engine.planner import _make_quality
    from paceforge.engine.vdot import paces_from_vdot
    from paceforge.engine.workouts import WorkoutFactory

    factory = WorkoutFactory(paces_from_vdot(50))
    early = _make_quality(factory, "vo2max", 8.0, week_in_phase=0, deload=False, week_km=32)
    late = _make_quality(factory, "vo2max", 8.0, week_in_phase=3, deload=False, week_km=32)
    assert late.estimated_duration_seconds > early.estimated_duration_seconds


def test_hyrox_plan_is_running_only():
    plan = generate_plan(_make_profile(), _make_goal(GoalType.HYROX, weeks_out=12))
    types = {w.workout_type for wk in plan.weeks for w in wk.workouts}
    assert WorkoutType.HYROX_MIXED not in types
    assert WorkoutType.CROSS_TRAINING not in types


def test_volume_anchored_to_athlete_not_fixed_table():
    prof = _make_profile()
    prof.weekly_mileage_km = 60
    # HYROX table peak for intermediate is a fixed 40 — anchoring must beat it.
    start, peak = _starting_and_peak_km(prof, GoalType.HYROX, table_peak=40)
    assert peak >= 60
    assert start >= peak * 0.7


class TestPlanGeneration:
    def test_half_marathon_plan_has_correct_weeks(self):
        plan = generate_plan(_make_profile(), _make_goal())
        assert plan.total_weeks == 12
        assert len(plan.weeks) == 12

    def test_marathon_plan_has_correct_weeks(self):
        goal = _make_goal(GoalType.MARATHON, weeks_out=18)
        plan = generate_plan(_make_profile(), goal)
        assert plan.total_weeks == 16
        assert len(plan.weeks) == 16

    def test_hyrox_plan_has_correct_weeks(self):
        goal = _make_goal(GoalType.HYROX, weeks_out=12)
        plan = generate_plan(_make_profile(), goal)
        assert plan.total_weeks == 10
        assert len(plan.weeks) == 10

    def test_plan_has_paces(self):
        plan = generate_plan(_make_profile(vo2_max=50), _make_goal())
        assert plan.easy_pace is not None
        assert plan.threshold_pace is not None
        assert plan.interval_pace is not None

    def test_each_week_has_workouts(self):
        plan = generate_plan(_make_profile(), _make_goal())
        for week in plan.weeks:
            assert len(week.workouts) > 0

    def test_plan_has_no_rest_placeholders(self):
        """Non-training days are implicit rest — the plan emits no rest entries."""
        plan = generate_plan(_make_profile(), _make_goal())
        rest_count = sum(
            1
            for week in plan.weeks
            for w in week.workouts
            if w.workout_type.value == "rest"
        )
        assert rest_count == 0

    def test_progressive_volume(self):
        plan = generate_plan(_make_profile(), _make_goal())
        # Week 1 should have less km than the peak week (ignoring taper)
        wk1_km = plan.weeks[0].total_distance_km or 0
        # Find max volume week (should be in Build/Peak phase)
        max_km = max(w.total_distance_km or 0 for w in plan.weeks)
        assert wk1_km < max_km

    def test_plan_without_vo2max_still_works(self):
        """Plan generation should handle missing VO2 max gracefully."""
        profile = UserFitnessProfile()
        plan = generate_plan(profile, _make_goal())
        assert plan.total_weeks > 0
        assert len(plan.weeks) > 0

    def test_workouts_have_variety(self):
        """Across all weeks, at least 4 different WorkoutType values should be used."""
        plan = generate_plan(_make_profile(), _make_goal())
        all_types = {
            w.workout_type
            for week in plan.weeks
            for w in week.workouts
        }
        # Filter out REST since it's not a "real" workout type for variety purposes
        non_rest_types = all_types - {WorkoutType.REST}
        assert len(non_rest_types) >= 4, f"Only found {len(non_rest_types)} types: {non_rest_types}"

    def test_workouts_have_purpose(self):
        """Non-rest workouts should have a purpose field set."""
        plan = generate_plan(_make_profile(), _make_goal())
        for week in plan.weeks:
            for w in week.workouts:
                if w.workout_type != WorkoutType.REST:
                    assert w.purpose is not None, (
                        f"Week {week.week_number}, workout '{w.name}' has no purpose"
                    )

    def test_weeks_have_focus(self):
        """Each week should have a non-empty focus field."""
        plan = generate_plan(_make_profile(), _make_goal())
        for week in plan.weeks:
            assert week.focus, f"Week {week.week_number} has empty focus"

    # ── Day-selection tests ──────────────────────────────────────────

    def test_3_day_plan_has_only_training_days(self):
        """With 3 training days, the week holds exactly those 3 — no rest entries."""
        goal = _make_goal(training_days=["tuesday", "thursday", "sunday"], long_run_day="sunday")
        plan = generate_plan(_make_profile(), goal)
        week = plan.weeks[0]
        rest = [w for w in week.workouts if w.workout_type == WorkoutType.REST]
        run = [w for w in week.workouts if w.workout_type != WorkoutType.REST]
        assert len(rest) == 0, f"Expected 0 rest days, got {len(rest)}"
        assert len(run) == 3, f"Expected 3 run days, got {len(run)}"

    def test_5_day_custom_days(self):
        """Workouts placed only on chosen training days."""
        chosen = ["monday", "wednesday", "friday", "saturday", "sunday"]
        goal = _make_goal(training_days=chosen, long_run_day="sunday")
        plan = generate_plan(_make_profile(), goal)
        week = plan.weeks[0]
        for w in week.workouts:
            if w.workout_type != WorkoutType.REST:
                day_name = list(_DAY_OFFSETS.keys())[w.scheduled_date.weekday()]
                assert day_name in chosen, f"{w.name} on {day_name} not in {chosen}"

    def test_long_run_on_chosen_day(self):
        """Long run must be on the specified long_run_day."""
        goal = _make_goal(training_days=["tuesday", "thursday", "saturday", "sunday"],
                         long_run_day="saturday")
        plan = generate_plan(_make_profile(), goal)
        for week in plan.weeks[:-1]:  # skip race week
            lr = [w for w in week.workouts if "Long" in w.name]
            if lr:
                assert lr[0].scheduled_date.weekday() == 5, (  # 5 = Saturday
                    f"Long run on weekday {lr[0].scheduled_date.weekday()}, expected 5"
                )

    def test_7_day_plan_no_rest(self):
        """A 7-day plan should have zero rest days (non-race weeks)."""
        all_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        goal = _make_goal(training_days=all_days, long_run_day="sunday")
        plan = generate_plan(_make_profile(), goal)
        week = plan.weeks[0]
        rest = [w for w in week.workouts if w.workout_type == WorkoutType.REST]
        assert len(rest) == 0, f"Expected 0 rest days in 7-day plan, got {len(rest)}"
