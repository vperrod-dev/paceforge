"""Tests for the training-load / recovery / wellbeing engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from paceforge.engine.load import (
    _trimp,
    compute_acwr,
    compute_ctl_atl_tsb,
    compute_hrv,
    compute_injury_spike,
    compute_load_recovery,
    compute_monotony_strain,
    compute_readiness_composite,
    compute_sleep,
)

# ── Lightweight test doubles (only the attrs the engine reads) ───────


@dataclass
class FakeActivity:
    activity_id: int
    start_time: datetime
    duration_seconds: float
    distance_meters: float
    avg_hr: int | None = None
    max_hr: int | None = None
    training_effect_aerobic: float | None = None
    training_effect_anaerobic: float | None = None
    activity_type: str = "running"


@dataclass
class FakeProfile:
    resting_hr: int = 50
    max_hr: int = 190
    training_status: str = "Productive"
    load_focus: str = "High Aerobic"
    training_readiness: float = 65.0
    training_load_7day: float = 300.0


_DAY0 = datetime(2026, 1, 1, 7, 0, 0)


def _run(day_offset: int, *, dur_min: float, hr: int, dist_m: float = 5000) -> FakeActivity:
    return FakeActivity(
        activity_id=day_offset,
        start_time=_DAY0 + timedelta(days=day_offset),
        duration_seconds=dur_min * 60,
        distance_meters=dist_m,
        avg_hr=hr,
    )


def _wellness(day_offset: int, **kw) -> dict:
    base = {"date": (_DAY0 + timedelta(days=day_offset)).date().isoformat()}
    base.update({k: kw.get(k) for k in kw})
    return base


# ── 1. TRIMP sanity ──────────────────────────────────────────────────


class TestTrimp:
    def test_zero_at_resting_hr(self):
        """At resting HR the heart-rate reserve is 0, so TRIMP is 0."""
        assert _trimp(3600, avg_hr=50, resting_hr=50, max_hr=190) == 0.0

    def test_moderate_session_value(self):
        """60 min at HRr=0.5 → 60×0.5×0.64×e^0.96 ≈ 50."""
        val = _trimp(3600, avg_hr=120, resting_hr=50, max_hr=190)
        assert 49 < val < 51

    def test_hrr_clamped_above_max(self):
        """avg_hr above max_hr clamps HRr to 1, not beyond."""
        val = _trimp(3600, avg_hr=210, resting_hr=50, max_hr=190)
        expected = 60 * 1.0 * 0.64 * math.exp(1.92)
        assert abs(val - expected) < 0.01


# ── 2. CTL/ATL/TSB convergence ───────────────────────────────────────


class TestCtlAtlTsb:
    def test_converges_to_constant_load(self):
        """Under constant daily load L, both CTL and ATL converge to L."""
        series = [{"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": 50.0} for i in range(120)]
        out = compute_ctl_atl_tsb(series)
        assert abs(out["ctl"] - 50.0) < 1.0
        assert abs(out["atl"] - 50.0) < 0.5

    def test_tsb_negative_after_hard_block(self):
        """A ramp to high load drives ATL above CTL → negative TSB (fatigued)."""
        easy = [{"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": 20.0} for i in range(60)]
        hard = [{"date": (_DAY0 + timedelta(days=60 + i)).date().isoformat(), "load": 120.0} for i in range(14)]
        out = compute_ctl_atl_tsb(easy + hard)
        assert out["tsb"] < 0
        assert out["friel_band"] in {"optimal", "high-risk"}


# ── 3. ACWR ──────────────────────────────────────────────────────────


class TestAcwr:
    def test_sweet_spot_on_steady_load(self):
        """Steady load → acute ≈ chronic → ACWR ~1.0 in the sweet spot."""
        series = [{"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": 40.0} for i in range(28)]
        out = compute_acwr(series)
        assert out["flag"] == "sweet-spot"
        assert 0.9 < out["acwr"] < 1.1

    def test_high_flag_on_spike(self):
        """A big jump in the last week pushes ACWR ≥ 1.5 → high flag."""
        base = [{"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": 20.0} for i in range(21)]
        spike = [{"date": (_DAY0 + timedelta(days=21 + i)).date().isoformat(), "load": 80.0} for i in range(7)]
        out = compute_acwr(base + spike)
        assert out["flag"] == "high"


# ── 4. Monotony ──────────────────────────────────────────────────────


class TestMonotony:
    def test_high_when_samey(self):
        """Identical nonzero days → very high (infinite) monotony, flagged."""
        series = [{"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": 50.0} for i in range(7)]
        out = compute_monotony_strain(series)
        assert out["concerning"] is True

    def test_low_when_varied(self):
        """Hard/rest alternation has high SD → low monotony, not concerning."""
        loads = [100, 0, 100, 0, 100, 0, 100]
        series = [
            {"date": (_DAY0 + timedelta(days=i)).date().isoformat(), "load": float(v)}
            for i, v in enumerate(loads)
        ]
        out = compute_monotony_strain(series)
        assert out["concerning"] is False


# ── 5. Injury spike tiers ────────────────────────────────────────────


class TestInjurySpike:
    def test_severe_tier_on_doubling(self):
        """A run more than 2× the prior longest is a >100% (severe) spike."""
        acts = [
            _run(0, dur_min=30, hr=140, dist_m=5000),
            _run(3, dur_min=70, hr=140, dist_m=12000),
        ]
        out = compute_injury_spike(acts)
        assert out["spikes"][-1]["tier"] == "severe"

    def test_no_spike_when_gradual(self):
        """A 10%-under jump produces no flagged spike."""
        acts = [
            _run(0, dur_min=30, hr=140, dist_m=10000),
            _run(3, dur_min=31, hr=140, dist_m=10500),
        ]
        out = compute_injury_spike(acts)
        assert out["spikes"] == []


# ── 6. HRV ───────────────────────────────────────────────────────────


class TestHrv:
    def test_within_normal_range(self):
        """Stable HRV keeps the latest value inside baseline ± 0.5·SD."""
        # Wobble around 60 but END at the mean so the latest sits mid-band.
        vals = [59.0, 61.0] * 14 + [58.0, 62.0, 60.0]
        history = [_wellness(i, hrv_last_night=vals[i]) for i in range(len(vals))]
        out = compute_hrv(history)
        assert out["status"] == "within"
        assert out["recommendation"].startswith("train")

    def test_below_detection(self):
        """A sharp drop on the latest night falls below the normal range."""
        history = [_wellness(i, hrv_last_night=60.0) for i in range(29)]
        history.append(_wellness(29, hrv_last_night=30.0))
        out = compute_hrv(history)
        assert out["status"] == "below"
        assert "back-off" in out["recommendation"]


# ── 7. Sleep debt ────────────────────────────────────────────────────


class TestSleep:
    def test_debt_accumulates_on_short_sleep(self):
        """14 nights of 6h each → ~28h debt vs an 8h target."""
        history = [
            _wellness(
                i,
                sleep_score=70,
                sleep_duration_seconds=6 * 3600,
                sleep_deep_seconds=3600,
                sleep_rem_seconds=3600,
                sleep_light_seconds=4 * 3600,
            )
            for i in range(14)
        ]
        out = compute_sleep(history)
        assert 27 < out["sleep_debt_hours"] < 29

    def test_no_debt_when_well_rested(self):
        """Full 8h nights accrue zero sleep debt."""
        history = [_wellness(i, sleep_score=85, sleep_duration_seconds=8 * 3600) for i in range(14)]
        out = compute_sleep(history)
        assert out["sleep_debt_hours"] == 0.0


# ── 8. Readiness composite ───────────────────────────────────────────


class TestReadiness:
    def test_score_within_bounds(self):
        """Readiness score is always clamped to 0..100."""
        hrv = {"status": "above"}
        sleep = {"availability": "ok", "score": 95, "sleep_debt_hours": 0}
        ctl = {"tsb": 25}
        bb = {"availability": "ok", "latest_high": 100}
        rhr = {"availability": "ok", "deviation_pct": -2}
        stress = {"availability": "ok", "latest_avg": 10}
        out = compute_readiness_composite(hrv, sleep, ctl, bb, rhr, stress)
        assert 0 <= out["score"] <= 100
        assert out["band"] == "green"

    def test_low_band_on_poor_signals(self):
        """Suppressed HRV, poor sleep, deep fatigue → low band."""
        hrv = {"status": "below"}
        sleep = {"availability": "ok", "score": 30, "sleep_debt_hours": 15}
        ctl = {"tsb": -35}
        bb = {"availability": "ok", "latest_high": 20}
        rhr = {"availability": "ok", "deviation_pct": 9}
        stress = {"availability": "ok", "latest_avg": 80}
        out = compute_readiness_composite(hrv, sleep, ctl, bb, rhr, stress)
        assert out["band"] == "low"


# ── 9. End-to-end & graceful degradation ─────────────────────────────


class TestComputeLoadRecovery:
    def test_returns_all_blocks(self):
        """The entry function returns every documented top-level block."""
        out = compute_load_recovery([], [], FakeProfile())
        expected = {
            "daily_load",
            "ctl_atl_tsb",
            "acwr",
            "monotony_strain",
            "ramp_rate",
            "injury_spike",
            "aerobic_anaerobic_split",
            "hrv",
            "resting_hr_trend",
            "sleep",
            "body_battery_trend",
            "stress_trend",
            "respiration_trend",
            "spo2_trend",
            "illness_watch",
            "overtraining_composite",
            "readiness_composite",
            "garmin_native",
        }
        assert set(out.keys()) == expected

    def test_accumulating_status_on_single_row_history(self):
        """A 1-row history tags trend blocks as 'accumulating', never raising."""
        history = [_wellness(0, hrv_last_night=55.0, resting_hr=48, sleep_score=80)]
        out = compute_load_recovery(history, [], FakeProfile())
        assert out["hrv"]["availability"]["status"] == "accumulating"
        assert out["ctl_atl_tsb"]["availability"]["status"] == "accumulating"

    def test_overtraining_escalates_to_deload(self):
        """Many concurrent red flags escalate the overtraining level to deload."""
        # Suppressed HRV for the whole window + elevated RHR + sleep debt + monotony.
        history = []
        for i in range(29):
            history.append(_wellness(i, hrv_last_night=60.0, resting_hr=48, sleep_score=80, sleep_duration_seconds=8 * 3600, stress_avg=70))
        # Latest nights: HRV crashes, RHR jumps, sleep short, stress high.
        for i in range(29, 36):
            history.append(_wellness(i, hrv_last_night=30.0, resting_hr=58, sleep_score=40, sleep_duration_seconds=5 * 3600, stress_avg=75))
        # Activities forming a monotonous, ramping hard block.
        acts = [_run(i, dur_min=70, hr=160, dist_m=12000) for i in range(36)]
        out = compute_load_recovery(history, acts, FakeProfile())
        assert out["overtraining_composite"]["level"] in {"caution", "deload"}
        assert out["overtraining_composite"]["count"] >= 2

    def test_garmin_native_passthrough(self):
        """Garmin native block passes through profile fields with labels."""
        out = compute_load_recovery([], [], FakeProfile())
        g = out["garmin_native"]
        assert g["training_status"] == "Productive"
        assert g["training_status_label"] is not None
        assert g["training_readiness"] == 65.0


class TestSRPEFallback:
    def test_hrless_strength_with_rpe_contributes_load(self):
        strength = FakeActivity(1, _DAY0, 3600, 0, avg_hr=None,
                                activity_type="strength_training")
        from paceforge.engine.load import compute_daily_load
        out = compute_daily_load([strength], 50, 190, rpe_map={1: {"rpe": 7}})
        assert out["availability"] == "ok"
        entry = out["per_activity"][0]
        assert entry["method"] == "srpe" and entry["trimp"] > 0
        assert out["unloaded_activities"] == []

    def test_hrless_without_rpe_is_reported_unloaded(self):
        strength = FakeActivity(1, _DAY0, 3600, 0, avg_hr=None,
                                activity_type="strength_training")
        from paceforge.engine.load import compute_daily_load
        out = compute_daily_load([strength], 50, 190)
        assert out["per_activity"] == []
        assert out["unloaded_activities"][0]["activity_id"] == 1

    def test_mixed_day_sums_trimp_and_srpe(self):
        run = FakeActivity(1, _DAY0, 3600, 10000, avg_hr=150)
        strength = FakeActivity(2, _DAY0.replace(hour=18), 3600, 0, avg_hr=None,
                                activity_type="strength_training")
        from paceforge.engine.load import compute_daily_load
        out = compute_daily_load([run, strength], 50, 190, rpe_map={2: {"rpe": 7}})
        methods = {e["method"] for e in out["per_activity"]}
        assert methods == {"trimp", "srpe"}
        day_total = out["series"][0]["load"]
        assert day_total > max(e["trimp"] for e in out["per_activity"])

    def test_srpe_calibration_is_in_trimp_ballpark(self):
        # 60-min RPE-7 strength ≈ 60-min steady HR run within a factor of ~1.5.
        run = FakeActivity(1, _DAY0, 3600, 10000, avg_hr=150)
        strength = FakeActivity(2, _DAY0 + timedelta(days=1), 3600, 0, avg_hr=None,
                                activity_type="strength_training")
        from paceforge.engine.load import compute_daily_load
        out = compute_daily_load([run, strength], 50, 190, rpe_map={2: {"rpe": 7}})
        trimp, srpe = (e["trimp"] for e in out["per_activity"])
        assert 0.6 < srpe / trimp < 1.6


# ── 10. Respiration / SpO2 / illness watch ───────────────────────────


class TestRespirationTrend:
    def _history(self, latest: float) -> list[dict]:
        rows = [_wellness(i, respiration_avg_sleep=14.0) for i in range(14)]
        rows.append(_wellness(14, respiration_avg_sleep=latest))
        return rows

    def test_elevated_when_1_5_over_baseline(self):
        from paceforge.engine.load import compute_respiration_trend
        assert compute_respiration_trend(self._history(15.6))["elevated"] is True

    def test_not_elevated_within_baseline(self):
        from paceforge.engine.load import compute_respiration_trend
        assert compute_respiration_trend(self._history(14.8))["elevated"] is False

    def test_accumulating_on_short_history(self):
        from paceforge.engine.load import compute_respiration_trend
        out = compute_respiration_trend([_wellness(0, respiration_avg_sleep=14.0)])
        assert out["availability"]["status"] == "accumulating"


class TestSpo2Trend:
    def test_low_below_absolute_floor(self):
        from paceforge.engine.load import compute_spo2_trend
        rows = [_wellness(0, spo2_avg=93.0)]
        assert compute_spo2_trend(rows)["low"] is True

    def test_low_on_two_point_drop_from_baseline(self):
        from paceforge.engine.load import compute_spo2_trend
        rows = [_wellness(i, spo2_avg=97.0) for i in range(10)]
        rows.append(_wellness(10, spo2_avg=95.0))
        assert compute_spo2_trend(rows)["low"] is True

    def test_ok_at_stable_baseline(self):
        from paceforge.engine.load import compute_spo2_trend
        rows = [_wellness(i, spo2_avg=96.0) for i in range(10)]
        assert compute_spo2_trend(rows)["low"] is False


class TestIllnessWatch:
    def test_none_without_respiratory_evidence(self):
        from paceforge.engine.load import compute_illness_watch
        out = compute_illness_watch(
            {"elevated": False}, {"low": False}, {"elevated": True}, {"status": "below"}
        )
        assert out["level"] == "none"

    def test_watch_on_single_respiratory_signal(self):
        from paceforge.engine.load import compute_illness_watch
        out = compute_illness_watch(
            {"elevated": True}, {"low": False}, {"elevated": False}, {"status": "within"}
        )
        assert out["level"] == "watch"

    def test_alert_when_corroborated(self):
        from paceforge.engine.load import compute_illness_watch
        out = compute_illness_watch(
            {"elevated": True}, {"low": False}, {"elevated": True}, {"status": "within"}
        )
        assert out["level"] == "alert"
