"""Parse a saved hyresult.com result page (no network)."""

from pathlib import Path

import pytest

from paceforge.hyrox.analyzer import analyze_race
from paceforge.hyrox.hyresult import HyresultScraper, parse_result

FIXTURE = (Path(__file__).parent / "fixtures" / "hyresult_berlin.html").read_text()


def test_parses_city_and_year():
    assert parse_result(FIXTURE).event_date == "Berlin 2026"


def test_parses_total_time():
    assert parse_result(FIXTURE).total_time_display == "1:06:19"


def test_overall_rank_is_per_race_not_season_cumulative():
    assert parse_result(FIXTURE).rank == "203"


def test_field_size():
    assert parse_result(FIXTURE).field_size == "4142"


def test_age_group_rank():
    assert parse_result(FIXTURE).rank_age_group == "12"


def test_age_group_bracket():
    assert parse_result(FIXTURE).age_group == "40-44"


def test_all_seventeen_splits_present():
    timed = [s for s in parse_result(FIXTURE).splits if s.time_seconds]
    assert len(timed) == 17


def test_split_carries_its_own_rank():
    skierg = next(s for s in parse_result(FIXTURE).splits if s.name == "SkiErg_1000m")
    assert skierg.rank == "236"


def test_analyze_emits_a_segment_per_split_in_race_order():
    segments = analyze_race(parse_result(FIXTURE))["segments"]
    assert len(segments) == 16


def test_analyze_computes_segment_percentile():
    segments = analyze_race(parse_result(FIXTURE))["segments"]
    skierg = next(s for s in segments if s["name"] == "SkiErg_1000m")
    assert skierg["percentile"] == 94  # rank 236 of 4142


def test_segments_carry_cumulative_time():
    segments = analyze_race(parse_result(FIXTURE))["segments"]
    assert segments[-1]["cumulative"] > segments[0]["cumulative"]


def test_result_ids_rejects_slug_with_path_traversal():
    with pytest.raises(ValueError, match="invalid hyresult athlete slug"):
        HyresultScraper().result_ids("../../etc/passwd")


def test_fetch_result_rejects_result_id_with_slash():
    with pytest.raises(ValueError, match="invalid hyresult result id"):
        HyresultScraper().fetch_result("ABC/../../admin")
