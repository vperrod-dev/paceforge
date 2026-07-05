"""Pace-duration curves, environmental normalization, effective VO2max."""
from dataclasses import dataclass
from datetime import date, datetime

from paceforge.engine.curves import compute_pace_curves
from paceforge.engine.durability import compute_effective_vo2max
from paceforge.engine.enviro import adjusted_pace, pace_adjustment_factor

TODAY = date(2026, 7, 3)


@dataclass
class _Act:
    activity_id: int
    start_time: datetime
    activity_type: str = "running"
    avg_pace_sec_per_km: float | None = None
    avg_hr: int | None = None
    duration_seconds: float = 3600


@dataclass
class _Profile:
    max_hr: int | None = 190


def _detail(pace_by_minute):
    """A series with one sample per minute at the given paces (sec/km)."""
    return {"series": [{"t": i * 60, "pace": p, "hr": 150}
                       for i, p in enumerate(pace_by_minute)]}


class TestPaceCurves:
    def test_best_short_effort_beats_average(self):
        # 40 easy minutes at 5:30/km with a 5-minute surge at 4:00/km.
        paces = [330.0] * 20 + [240.0] * 5 + [330.0] * 15
        acts = [_Act(1, datetime(2026, 6, 20, 7, 0))]
        out = compute_pace_curves(acts, {1: _detail(paces)}, today=TODAY)
        assert out["available"]
        assert out["recent_90d"][300] < 250        # the surge is found
        assert out["recent_90d"][1200] > 250       # long windows include easy running

    def test_fatigued_curve_excludes_fresh_start(self):
        # Fast opening 10 minutes, slow after 25 min — the fatigued curve must
        # only see the late (slow) part.
        paces = [240.0] * 10 + [330.0] * 40
        acts = [_Act(1, datetime(2026, 6, 20, 7, 0))]
        out = compute_pace_curves(acts, {1: _detail(paces)}, today=TODAY)
        assert out["fatigued_90d"][300] > out["recent_90d"][300]
        assert out["fatigue_cost_pct"][300] > 0

    def test_unavailable_without_series(self):
        acts = [_Act(1, datetime(2026, 6, 20, 7, 0))]
        out = compute_pace_curves(acts, {}, today=TODAY)
        assert out["available"] is False


class TestEnviro:
    def test_cool_weather_is_neutral(self):
        assert pace_adjustment_factor(12.0, 50) == 1.0
        assert adjusted_pace(330.0, {"temp_c": 12, "humidity": 50}) == 330.0

    def test_heat_costs_pace(self):
        hot = pace_adjustment_factor(28.0, 40)
        hotter = pace_adjustment_factor(32.0, 80)
        assert 1.0 < hot < hotter <= 1.12

    def test_adjusted_pace_is_faster_on_hot_days(self):
        adj = adjusted_pace(330.0, {"temp_c": 30, "humidity": 75})
        assert adj < 330.0

    def test_missing_weather_is_identity(self):
        assert adjusted_pace(330.0, None) == 330.0
        assert adjusted_pace(None, {"temp_c": 30}) is None


class TestEffectiveVO2max:
    def _runs(self, pace, hr, n=6):
        return [_Act(i, datetime(2026, 6, 1 + i * 3, 7, 0),
                     avg_pace_sec_per_km=pace, avg_hr=hr) for i in range(n)]

    def test_faster_at_same_hr_scores_higher(self):
        prof = _Profile()
        slow = compute_effective_vo2max(self._runs(330.0, 150), {}, prof)
        fast = compute_effective_vo2max(self._runs(290.0, 150), {}, prof)
        assert slow["available"] and fast["available"]
        assert fast["current"] > slow["current"]

    def test_needs_max_hr(self):
        out = compute_effective_vo2max(self._runs(330.0, 150), {}, _Profile(max_hr=None))
        assert out["available"] is False

    def test_hot_run_is_conditions_adjusted_upward(self):
        prof = _Profile()
        neutral = compute_effective_vo2max(self._runs(330.0, 150), {}, prof)
        hot_details = {i: {"weather": {"temp_c": 30, "humidity": 75}} for i in range(6)}
        hot = compute_effective_vo2max(self._runs(330.0, 150), hot_details, prof)
        assert hot["current"] > neutral["current"]
