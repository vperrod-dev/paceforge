"""Schedule a class as a first-class calendar item (2026-08-10 decoupling)."""
from datetime import date, datetime

from paceforge import actions, store
from paceforge.models.profile import RecentActivity


def test_add_session_creates_calendar_item():
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45,
                                 name="Hyrox Class")
    items = store.load_calendar()
    assert len(items) == 1
    assert items[0].title == "Hyrox Class" and items[0].sport == "HYROX"
    assert result["session_ids"] == [items[0].item_id]


def test_add_session_needs_no_plan_and_touches_none():
    assert store.load_plan() is None
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=45)
    assert store.load_plan() is None          # the whole point of the decoupling
    assert len(store.load_calendar()) == 1


def test_add_session_matches_existing_garmin_activity_same_day():
    store.save_activities([RecentActivity(
        activity_id=1, name="Cardio", activity_type="indoor_cardio",
        start_time=datetime(2026, 8, 4, 7, 0), duration_seconds=2700, distance_meters=0,
    )])
    actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45)
    item = store.load_calendar()[0]
    assert item.matched_activity_ids == ["1"] and item.completed


def test_generic_item_never_claims_a_run():
    store.save_activities([RecentActivity(
        activity_id=2, name="Morning Run", activity_type="running",
        start_time=datetime(2026, 8, 4, 7, 0), duration_seconds=1800, distance_meters=5000,
    )])
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=45)
    item = store.load_calendar()[0]
    assert not item.completed and item.matched_activity_ids == []


def test_add_session_repeat_weekly_schedules_each_week():
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45,
                                 name="Hyrox Class", repeat_weeks=3)
    dates = sorted(i.date for i in store.load_calendar())
    assert dates == [date(2026, 8, 4), date(2026, 8, 11), date(2026, 8, 18)]
    assert len(result["session_ids"]) == 3


def test_add_session_repeat_weeks_clamped_to_max():
    result = actions.add_session(session_date="2026-08-04", sport="HYROX", minutes=45,
                                 repeat_weeks=999)
    assert result["repeat_weeks"] == 52


def test_absurd_duration_is_clamped_to_a_plausible_class_length():
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=99999)
    assert store.load_calendar()[0].duration_min == 480


def test_negative_duration_is_clamped_up():
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=-30)
    assert store.load_calendar()[0].duration_min == 5


def test_overlong_name_is_truncated_so_garmin_push_does_not_choke():
    actions.add_session(session_date="2026-08-04", sport="Cardio", minutes=45, name="X" * 500)
    item = store.load_calendar()[0]
    assert len(item.title) == 120
    assert len(actions._item_to_workout(item).name) <= 120


def test_bike_item_matches_app_recorded_ride_same_day():
    # App rides live in data/bike/rides.json, never on Garmin — the matcher must see them.
    (store.DATA_DIR / "bike").mkdir()
    (store.DATA_DIR / "bike" / "rides.json").write_text(
        '{"rides": [{"date": "2026-08-04T14:42:33", "workout": "4x8 VO2", '
        '"duration_sec": 3269, "tss": 82.2, "source": "web"}]}')
    actions.add_session(session_date="2026-08-04", sport="Bike", minutes=45,
                        name="Indoor cycling")
    item = store.load_calendar()[0]
    assert item.matched_activity_ids == ["bike:2026-08-04T14:42:33"] and item.completed
