"""Runalyze-style independent race prognosis.

Two ingredients, both device-independent (no Garmin race predictor involved):

1. **Effective VO2max** — every recent run with HR + pace becomes a VO2max
   estimate: Daniels' VO2-at-pace divided by the fraction of VO2max the HR
   says was used (Swain's %HRmax→%VO2max regression). Recent runs weigh more
   (exponential decay, 30-day half-life), so the number tracks current shape.
2. **Race-shape correction** — VO2max alone overestimates long-race times for
   under-trained athletes, so an 8-week mileage + long-run factor scales the
   Daniels prediction (Runalyze's "marathon shape", generalised to the goal
   distance).

Reference: runalyze.com glossary (effective VO2max, marathon shape, prognosis).
"""

from __future__ import annotations

from datetime import date, timedelta

# Reuse form.py's run-type filter and tolerant date parsing; vdot.py owns the
# Daniels prediction inverse — never re-derive it here.
from paceforge.engine.form import _RUN_TYPES, _when
from paceforge.engine.vdot import predict_time

_LOOKBACK_DAYS = 90
_SHAPE_WINDOW_DAYS = 56  # 8 weeks
_HALF_LIFE_DAYS = 30.0
_MIN_RUN_METERS = 3000  # shorter runs: HR/pace ratio too noisy (warmup-dominated)
# Profile may lack max_hr entirely; 190 ≈ population median for this app's
# demographic — a wrong guess shifts all runs equally, trends stay intact.
_FALLBACK_MAX_HR = 190
# Weekly-km reference that counts as "fully prepared" for a half marathon;
# scaled linearly to other goal distances.
_REF_WEEKLY_KM_HM = 40.0
_HM_KM = 21.0975


def _vo2_at_pace(pace_sec_per_km: float) -> float:
    """Daniels & Gilbert oxygen cost of a running pace (v in m/min).

    Same polynomial vdot.py uses inside vdot_from_race; that file exposes no
    standalone helper and is off-limits to edit, hence the one local line.
    """
    v = 60000.0 / pace_sec_per_km
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _run_effective_vo2max(a, max_hr: float) -> float | None:
    """One run → effective VO2max, or None when the run can't support it."""
    hr = getattr(a, "avg_hr", None)
    pace = getattr(a, "avg_pace_sec_per_km", None)
    dist = getattr(a, "distance_meters", None)
    if not hr or not pace or not dist or dist < _MIN_RUN_METERS:
        return None
    # Swain et al.: %HRmax = 0.64*%VO2max + 0.37, inverted. Clamped because
    # very easy jogs push the regression outside its valid range and a tiny
    # denominator would explode the estimate.
    pct_vo2max = (hr / max_hr - 0.37) / 0.64
    pct_vo2max = min(max(pct_vo2max, 0.5), 1.0)
    return _vo2_at_pace(pace) / pct_vo2max


def compute_prognosis(activities: list, details: dict | None, profile,
                      goal_distance_km: float = _HM_KM,
                      goal_time_sec: float | None = None,
                      target_date=None,
                      prior_vdot: float | None = None) -> dict:
    """Independent race prognosis from recent runs. target_date is accepted for
    API symmetry but unused — the prognosis describes today's shape.

    prior_vdot: VDOT from an actual stated race (the intake). The HR→%VO2max
    regression inflates hard on low-HR easy runs (observed: 69.5 for a 52:30
    10K athlete, VDOT 37.8), so when a race prior exists the HR-derived value
    is clamped to prior×[0.90, 1.12] — fitness can still be seen moving, but
    an actual race performance anchors the scale."""
    today = date.today()
    max_hr = float(getattr(profile, "max_hr", None) or _FALLBACK_MAX_HR)

    # ── effective VO2max, recency-weighted ───────────────────────────
    cutoff = today - timedelta(days=_LOOKBACK_DAYS)
    series: list[dict] = []
    num = den = 0.0
    runs_56d: list[tuple[date, float]] = []  # (date, km) for the shape factor
    for a in activities:
        d = _when(a)
        if d is None or d < cutoff:
            continue
        if str(getattr(a, "activity_type", "")).lower() not in _RUN_TYPES:
            continue
        km = (getattr(a, "distance_meters", None) or 0) / 1000.0
        if km and d >= today - timedelta(days=_SHAPE_WINDOW_DAYS):
            runs_56d.append((d, km))
        vo2 = _run_effective_vo2max(a, max_hr)
        if vo2 is None:
            continue
        num += 0.5 ** ((today - d).days / _HALF_LIFE_DAYS) * vo2
        den += 0.5 ** ((today - d).days / _HALF_LIFE_DAYS)
        series.append({"date": d.isoformat(), "effective_vo2max": round(vo2, 1)})
    if not den:
        return {"available": False, "goal_time_sec": goal_time_sec, "series": []}
    series.sort(key=lambda x: x["date"])
    eff_vo2max = num / den
    if prior_vdot:
        eff_vo2max = min(max(eff_vo2max, prior_vdot * 0.90), prior_vdot * 1.12)

    # ── race-shape correction ────────────────────────────────────────
    weekly_km = sum(km for _, km in runs_56d) / (_SHAPE_WINDOW_DAYS / 7)
    longest_km = max((km for _, km in runs_56d), default=0.0)
    ref_weekly = _REF_WEEKLY_KM_HM * (goal_distance_km / _HM_KM)
    mileage_c = min(weekly_km / ref_weekly, 1.05)  # linear below ref, capped above
    long_c = min(longest_km / (0.75 * goal_distance_km), 1.0)
    shape = min(max(mileage_c * 2 / 3 + long_c * 1 / 3, 0.6), 1.05)

    # ── prognosis ────────────────────────────────────────────────────
    base_time = predict_time(goal_distance_km * 1000.0, eff_vo2max)
    # Linear penalty, monotonic in shape: each point of missing shape costs
    # 0.6 points of time (shape 0.6 → +24%, shape 1 → 0, shape 1.05 → −3%).
    prognosis_time = base_time * (1 + (1 - shape) * 0.6)

    if goal_time_sec is None:
        verdict = None
    elif goal_time_sec >= prognosis_time:  # goal slower than prognosis → comfortable
        verdict = "on_track"
    elif goal_time_sec >= prognosis_time * 0.97:  # within 3% faster → reachable stretch
        verdict = "stretch"
    else:
        verdict = "unrealistic"

    return {
        "available": True,
        "effective_vo2max": round(eff_vo2max, 1),
        "base_time_sec": round(base_time),
        "shape": {
            "factor": round(shape, 3),
            "weekly_km_avg": round(weekly_km, 1),
            "longest_run_km": round(longest_km, 1),
            "components": {"mileage": round(mileage_c, 3), "long_run": round(long_c, 3)},
        },
        "prognosis_time_sec": round(prognosis_time),
        "prognosis_pace_sec_km": round(prognosis_time / goal_distance_km, 1),
        "goal_time_sec": goal_time_sec,
        "goal_verdict": verdict,
        "series": series,
    }
