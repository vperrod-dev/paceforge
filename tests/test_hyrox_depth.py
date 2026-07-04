"""Race-analysis depth: waterfall, pacing quality, roxzone analysis, trends."""
from paceforge.hyrox.analyzer import analyze_race, compute_race_progression
from paceforge.hyrox.models import HyroxRaceResult, HyroxSplit


def _race(runs=None, stations=None, roxzone=420.0, rank="100", field="1000",
          division="HYROX", age_group="40-44"):
    runs = runs or [330.0] * 8
    stations = stations or {
        "SkiErg_1000m": 260, "Sled_Push_50m": 175, "Sled_Pull_50m": 290,
        "Burpee_Broad_Jump_80m": 220, "Row_1000m": 250, "Farmers_Carry_200m": 145,
        "Sandbag_Lunges_100m": 300, "Wall_Balls": 280,
    }
    splits = [HyroxSplit(name=f"Running_{i+1}", time_seconds=t, rank="200", field_size=field)
              for i, t in enumerate(runs)]
    splits += [HyroxSplit(name=k, time_seconds=v, rank="300", field_size=field)
               for k, v in stations.items()]
    splits.append(HyroxSplit(name="Roxzone_Time", time_seconds=roxzone, rank="", field_size=""))
    total = sum(runs) + sum(stations.values()) + roxzone
    return HyroxRaceResult(total_time_seconds=total, rank=rank, field_size=field,
                           division=division, age_group=age_group, splits=splits,
                           event_date="Dublin 2025", city="Dublin")


class TestWaterfall:
    def test_only_positive_gaps_counted_and_sorted(self):
        out = analyze_race(_race(), gender="M")
        wf = out["time_lost"]["vs_top3"]
        assert wf["items"] == sorted(wf["items"], key=lambda i: i["seconds"], reverse=True)
        assert all(i["seconds"] > 0 for i in wf["items"])
        assert wf["total"] == round(sum(i["seconds"] for i in wf["items"]), 1)

    def test_roxzone_included_when_over_benchmark(self):
        out = analyze_race(_race(roxzone=600.0), gender="M")
        names = [i["name"] for i in out["time_lost"]["vs_field"]["items"]]
        assert "Roxzone_Time" in names


class TestPacingQuality:
    def test_even_pacing_scores_high(self):
        out = analyze_race(_race(runs=[330, 332, 331, 333, 334, 332, 331, 333]))
        pq = out["pacing_quality"]
        assert pq["available"] and pq["score"] >= 90
        assert any("Elite-level pacing" in f for f in pq["flags"])

    def test_fast_start_flagged(self):
        out = analyze_race(_race(runs=[300, 320, 330, 340, 350, 360, 370, 380]))
        pq = out["pacing_quality"]
        assert pq["score"] < 60
        assert any("too fast" in f for f in pq["flags"])
        assert any("collapse" in f or "slowest" in f for f in pq["flags"])


class TestRoxzoneAnalysis:
    def test_per_pass_and_recoverable(self):
        out = analyze_race(_race(roxzone=480.0))
        rz = out["roxzone_analysis"]
        assert rz["available"] and rz["per_pass_seconds"] == 30.0
        assert rz["recoverable_seconds"] == 210.0  # vs elite 270s total


class TestSegments:
    def test_cumulative_gap_monotone_when_slower_everywhere(self):
        out = analyze_race(_race())
        gaps = [s["cumulative_gap_top3"] for s in out["segments"]]
        assert gaps == sorted(gaps)  # every segment slower than top-3 → gap only grows
        assert gaps[-1] > 0


class TestPercentileTrend:
    def test_overall_and_station_percentiles(self):
        races = [_race(rank="500", field="1000"), _race(rank="250", field="1000")]
        prog = compute_race_progression(races)
        overall = prog["percentile_trend"]["overall"]
        assert [p["percentile"] for p in overall] == [50, 75]
        stations = prog["percentile_trend"]["stations"]
        assert len(stations["SkiErg_1000m"]) == 2
        assert stations["Running_1"][0]["percentile"] == 80  # rank 200/1000
