"""Race-time prediction, career pacing-strategy effectiveness, and station-attributed fade."""
from paceforge.hyrox.analyzer import (
    compute_compromise_by_station,
    compute_pacing_strategy_effectiveness,
    predict_next_race,
)
from paceforge.hyrox.models import HyroxRaceResult, HyroxSplit


def _race(total_seconds, event_date, runs=None, stations=None, roxzone=420.0,
          rank="", field="", division="HYROX"):
    runs = runs or [330.0] * 8
    stations = stations or {
        "SkiErg_1000m": 260, "Sled_Push_50m": 175, "Sled_Pull_50m": 290,
        "Burpee_Broad_Jump_80m": 220, "Row_1000m": 250, "Farmers_Carry_200m": 145,
        "Sandbag_Lunges_100m": 300, "Wall_Balls": 280,
    }
    splits = [HyroxSplit(name=f"Running_{i+1}", time_seconds=t) for i, t in enumerate(runs)]
    splits += [HyroxSplit(name=k, time_seconds=v) for k, v in stations.items()]
    splits.append(HyroxSplit(name="Roxzone_Time", time_seconds=roxzone))
    return HyroxRaceResult(total_time_seconds=total_seconds, division=division,
                           event_date=event_date, city=event_date, splits=splits,
                           rank=rank, field_size=field)


class TestPredictNextRace:
    def test_no_races_falls_back_to_cohort(self):
        out = predict_next_race([], gender="M")
        assert out["method"] == "cohort_field_average"
        assert out["predicted_seconds"] > 0

    def test_single_race_uses_its_own_time(self):
        out = predict_next_race([_race(5400, "2025-01-01")])
        assert out["method"] == "latest_race"
        assert out["predicted_seconds"] == 5400

    def test_improving_trend_extrapolates_faster(self):
        races = [_race(6000, "2024-01-01"), _race(5800, "2024-06-01"), _race(5600, "2025-01-01")]
        out = predict_next_race(races)
        assert out["method"] == "trend"
        assert out["trend"] == "improving"
        assert out["predicted_seconds"] < 5600

    def test_prediction_clamped_to_observed_range(self):
        # A wild slope shouldn't be allowed to extrapolate outside real bounds.
        races = [_race(10000, "2024-01-01"), _race(4000, "2024-02-01")]
        out = predict_next_race(races)
        assert 4000 * 0.85 <= out["predicted_seconds"] <= 10000 * 1.3


class TestPacingStrategyEffectiveness:
    def test_unavailable_with_fewer_than_three_races(self):
        races = [_race(5400, "2025-01-01", rank="100", field="1000")]
        assert compute_pacing_strategy_effectiveness(races)["available"] is False

    def test_less_fade_correlates_with_better_percentile(self):
        # Least fade paired with best percentile, most fade with worst percentile.
        races = [
            _race(5400, "2024-01-01", runs=[280, 285, 290, 295, 300, 305, 310, 330],
                  rank="900", field="1000"),
            _race(5300, "2024-06-01", runs=[290, 293, 296, 299, 302, 305, 308, 311],
                  rank="500", field="1000"),
            _race(5200, "2025-01-01", runs=[300] * 8, rank="100", field="1000"),
        ]
        out = compute_pacing_strategy_effectiveness(races)
        assert out["available"] and out["races_used"] == 3
        assert out["correlation"] < -0.3

    def test_missing_rank_data_excluded(self):
        races = [
            _race(5400, "2024-01-01", rank="", field=""),
            _race(5300, "2024-06-01", rank="500", field="1000"),
            _race(5200, "2025-01-01", rank="100", field="1000"),
        ]
        out = compute_pacing_strategy_effectiveness(races)
        assert out["available"] is False
        assert out["races_used"] == 2


class TestCompromiseByStation:
    def test_unavailable_with_no_races(self):
        assert compute_compromise_by_station([])["available"] is False

    def test_flags_worst_transition_first(self):
        # Fade evenly except a big spike right after Sled Pull (run 4).
        races = [_race(5400, "2025-01-01", runs=[300, 305, 310, 360, 315, 320, 325, 330])]
        out = compute_compromise_by_station(races)
        assert out["available"]
        assert out["stations"][0]["run_position"] == 4
        assert out["stations"][0]["station"] == "Sled_Pull_50m"
        assert out["stations"][0]["excess_fade_pct"] > 0

    def test_aggregates_across_multiple_races(self):
        races = [
            _race(5400, "2025-01-01", runs=[300, 310, 320, 330, 340, 350, 360, 370]),
            _race(5300, "2025-06-01", runs=[295, 305, 315, 325, 335, 345, 355, 365]),
        ]
        out = compute_compromise_by_station(races)
        assert all(s["races_used"] == 2 for s in out["stations"])
