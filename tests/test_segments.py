"""HYROX auto-segmentation from Garmin typed splits."""

from paceforge.engine.segments import (
    classify_split,
    segment_activity,
    segment_hyrox_activities,
)
from paceforge.models.profile import RecentActivity


def _detail(*types_dur):
    return {"typed_splits": [
        {"type": t, "duration_s": d, "distance_m": dist}
        for t, d, dist in types_dur
    ]}


def test_run_split_classifies_as_run():
    assert classify_split("RWD_RUN") == "run"


def test_stand_split_classifies_as_station():
    assert classify_split("RWD_STAND") == "station"


def test_walk_split_classifies_as_roxzone():
    assert classify_split("RWD_WALK") == "roxzone"


def test_unknown_split_type_is_unclassified():
    assert classify_split("SWIM_LAP") is None


def test_segment_activity_sums_station_duration():
    out = segment_activity(_detail(("RWD_STAND", 200, 0), ("RWD_STAND", 100, 0)))
    assert out["segments"]["station"]["duration_s"] == 300.0


def test_segment_activity_share_is_percent_of_total_time():
    out = segment_activity(_detail(("RWD_RUN", 300, 1000), ("RWD_STAND", 100, 0)))
    assert out["segments"]["run"]["share_pct"] == 75.0


def test_segment_activity_returns_none_without_typed_splits():
    assert segment_activity({"activity_id": 1}) is None


def test_segment_activity_returns_none_when_no_type_is_recognised():
    assert segment_activity(_detail(("SWIM_LAP", 300, 0))) is None


def test_segment_hyrox_activities_skips_activities_without_details():
    act = RecentActivity(activity_id=9, name="sim", activity_type="fitness_equipment",
                         start_time="2026-06-20T07:00:00", distance_meters=8000,
                         duration_seconds=3600)
    assert segment_hyrox_activities([act], {}) == []


def test_segment_hyrox_activities_tags_date_from_activity():
    act = RecentActivity(activity_id=9, name="sim", activity_type="fitness_equipment",
                         start_time="2026-06-20T07:00:00", distance_meters=8000,
                         duration_seconds=3600)
    out = segment_hyrox_activities([act], {9: _detail(("RWD_RUN", 300, 1000))})
    assert out[0]["date"] == "2026-06-20"
