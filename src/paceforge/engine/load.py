"""Training-load, recovery & wellbeing metrics from Garmin wellness history.

Sports-science computations: Banister TRIMP, CTL/ATL/TSB (Performance Manager),
ACWR, Foster monotony/strain, HRV (lnRMSSD) baselines, sleep debt, and composite
overtraining / readiness scores. Pure stdlib (EWMA & regression by hand).

Every block degrades gracefully on missing data: instead of raising it tags the
block 'ok' or {'status': 'accumulating', 'have_days': N, 'need_days': M}.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

# ── Window constants (days) for trend metrics ────────────────────────
_HRV_BASELINE_DAYS = 7
_HRV_REF_DAYS = 60
_RHR_BASELINE_DAYS = 7
_SLEEP_DEBT_NIGHTS = 14
_SLEEP_TARGET_SECONDS = 8 * 3600
_TE_WINDOW_DAYS = 28
_ACWR_ACUTE_DAYS = 7
_ACWR_CHRONIC_WEEKS = 3
_MONOTONY_WINDOW_DAYS = 7
_CTL_TAU = 42
_ATL_TAU = 7
_INJURY_LOOKBACK_DAYS = 30
_RESP_BASELINE_DAYS = 14
_SPO2_BASELINE_DAYS = 14


def _accumulating(have: int, need: int) -> dict[str, Any]:
    """Standard 'not enough history yet' availability tag."""
    return {"status": "accumulating", "have_days": have, "need_days": need}


# ── Daily load (Banister TRIMP) ──────────────────────────────────────


@dataclass
class ActivityLoad:
    activity_id: Any
    date: str
    trimp: float
    activity_type: str
    method: str = "trimp"  # trimp (HR-based) | srpe (athlete-rated)


def _trimp(duration_seconds: float, avg_hr: int, resting_hr: int, max_hr: int) -> float:
    """Banister TRIMP: duration_min × HRr × 0.64 × e^(1.92×HRr).

    HRr is the heart-rate reserve fraction, clamped to [0, 1] so noisy HR or a
    bad resting/max profile cannot push the exponential to absurd values.
    """
    denom = max_hr - resting_hr
    if denom <= 0:
        return 0.0
    hrr = (avg_hr - resting_hr) / denom
    hrr = min(1.0, max(0.0, hrr))
    duration_min = duration_seconds / 60.0
    return duration_min * hrr * 0.64 * math.exp(1.92 * hrr)


# Foster session-RPE (rpe × minutes) lands on a different scale than Banister
# TRIMP; this constant bridges them so both pool into one CTL/ATL series. It is
# a heuristic: 0.26 puts a 60-min RPE-7 session (420 sRPE → ~109) at the TRIMP
# of a comparable 60-min moderately-hard HR session (~108 at HR 150 with
# rest 50 / max 190). The per-entry `method` tag means it can be re-scaled
# later without losing data.
_SRPE_TO_TRIMP = 0.26


def _srpe_load(duration_min: float, rpe: int) -> float:
    """Foster session-RPE converted to the TRIMP scale (see _SRPE_TO_TRIMP)."""
    return duration_min * rpe * _SRPE_TO_TRIMP


# Coggan TSS is also its own scale; 1.5 puts a 60-min IF-0.85 ride (72 TSS →
# ~108) at the TRIMP of a comparable moderately-hard HR hour (~108 at HR 150
# with rest 50 / max 190). Same re-scalable heuristic as _SRPE_TO_TRIMP —
# the per-entry `method` tag ("tss") keeps the original unit recoverable.
_TSS_TO_TRIMP = 1.5


def _activity_date(act: Any) -> str:
    """Normalise an activity's start_time to a YYYY-MM-DD string."""
    st = getattr(act, "start_time", None)
    if isinstance(st, (datetime, date)):
        return st.date().isoformat() if isinstance(st, datetime) else st.isoformat()
    return str(st)[:10]


def compute_daily_load(activities: list, resting_hr: int, max_hr: int,
                       rpe_map: dict | None = None,
                       bike_rides: list[dict] | None = None) -> dict[str, Any]:
    """Per-activity load (TRIMP, with sRPE fallback) and a daily-summed series.

    HR-based TRIMP underrates or drops strength/HYROX work (high muscular load,
    low-or-missing HR); an athlete RPE entry (rpe_map, keyed by activity_id)
    lets an HR-less session still count. Sessions with neither HR nor RPE are
    reported in `unloaded_activities` so the UI can ask for a rating.

    bike_rides are the app-recorded indoor rides (data/bike/rides.json) — they
    never reach Garmin, so they enter here: power-based TSS when present
    (bridged via _TSS_TO_TRIMP), else TRIMP from the strap HR.
    """
    rpe_map = rpe_map or {}
    per_activity: list[ActivityLoad] = []
    unloaded: list[dict] = []
    daily: dict[str, float] = {}
    for act in activities:
        avg_hr = getattr(act, "avg_hr", None)
        dur = getattr(act, "duration_seconds", None) or 0.0
        if dur <= 0:
            continue
        d = _activity_date(act)
        aid = getattr(act, "activity_id", None)
        if avg_hr is not None:
            load, method = _trimp(dur, avg_hr, resting_hr, max_hr), "trimp"
        else:
            entry = rpe_map.get(aid) or {}
            rpe = entry.get("rpe")
            if not rpe:
                unloaded.append({
                    "activity_id": aid, "date": d,
                    "activity_type": getattr(act, "activity_type", "unknown"),
                    "name": getattr(act, "name", None),
                })
                continue
            load, method = _srpe_load(dur / 60.0, int(rpe)), "srpe"
        per_activity.append(
            ActivityLoad(
                activity_id=aid,
                date=d,
                trimp=round(load, 2),
                activity_type=getattr(act, "activity_type", "unknown"),
                method=method,
            )
        )
        daily[d] = daily.get(d, 0.0) + load

    for ride in bike_rides or []:
        dur = ride.get("duration_sec") or 0
        if dur <= 0:
            continue
        d = str(ride.get("date", ""))[:10]
        tss_val, avg_hr = ride.get("tss"), ride.get("avg_hr")
        if tss_val is not None:
            load, method = tss_val * _TSS_TO_TRIMP, "tss"
        elif avg_hr is not None:
            load, method = _trimp(dur, avg_hr, resting_hr, max_hr), "trimp"
        else:
            unloaded.append({
                "activity_id": f"bike:{ride.get('date')}", "date": d,
                "activity_type": "indoor_cycling", "name": ride.get("workout"),
            })
            continue
        per_activity.append(
            ActivityLoad(
                activity_id=f"bike:{ride.get('date')}",
                date=d,
                trimp=round(load, 2),
                activity_type="indoor_cycling",
                method=method,
            )
        )
        daily[d] = daily.get(d, 0.0) + load

    if not daily:
        return {"availability": _accumulating(0, 1), "series": [], "per_activity": [],
                "unloaded_activities": unloaded}

    series = [{"date": d, "load": round(v, 2)} for d, v in sorted(daily.items())]
    return {
        "availability": "ok",
        "series": series,
        "per_activity": [vars(a) for a in per_activity],
        "unloaded_activities": unloaded,
    }


def _continuous_daily_load(series: list[dict]) -> list[tuple[date, float]]:
    """Fill zero-load days so EWMA runs over a continuous daily timeline."""
    if not series:
        return []
    points = {date.fromisoformat(p["date"]): p["load"] for p in series}
    start, end = min(points), max(points)
    out: list[tuple[date, float]] = []
    cur = start
    while cur <= end:
        out.append((cur, points.get(cur, 0.0)))
        cur += timedelta(days=1)
    return out


# ── CTL / ATL / TSB (Banister / TrainingPeaks Performance Manager) ───


def _friel_band(tsb: float) -> str:
    """Friel's Training Stress Balance interpretation bands."""
    if tsb > 5:
        return "fresh"
    if tsb > -10:
        return "grey"
    if tsb >= -30:
        return "optimal"
    return "high-risk"


def compute_ctl_atl_tsb(load_series: list[dict]) -> dict[str, Any]:
    """EWMA of daily load: CTL (τ=42, fitness) and ATL (τ=7, fatigue).

    X_today = X_prev*(1−1/τ) + load_today/τ. Seeded from the mean of the first
    two weeks so short timelines don't start cold at zero. TSB uses yesterday's
    CTL−ATL (the freshness you carry into today).
    """
    timeline = _continuous_daily_load(load_series)
    if not timeline:
        return {"availability": _accumulating(0, 7)}

    seed = sum(v for _, v in timeline[:14]) / min(len(timeline), 14)
    ctl = atl = seed
    series: list[dict] = []
    prev_ctl = prev_atl = seed
    for d, load in timeline:
        tsb = prev_ctl - prev_atl  # freshness carried into today
        prev_ctl, prev_atl = ctl, atl
        ctl = ctl * (1 - 1 / _CTL_TAU) + load / _CTL_TAU
        atl = atl * (1 - 1 / _ATL_TAU) + load / _ATL_TAU
        series.append(
            {
                "date": d.isoformat(),
                "ctl": round(ctl, 2),
                "atl": round(atl, 2),
                "tsb": round(tsb, 2),
            }
        )

    cur_tsb = round(prev_ctl - prev_atl, 2)
    return {
        "availability": "ok",
        "ctl": round(ctl, 2),
        "atl": round(atl, 2),
        "tsb": cur_tsb,
        "friel_band": _friel_band(cur_tsb),
        "series": series,
    }


# ── ACWR (acute:chronic workload ratio) ──────────────────────────────


def compute_acwr(load_series: list[dict]) -> dict[str, Any]:
    """Uncoupled ACWR = last-7d load / mean weekly load of the prior 3 weeks.

    NOTE: ACWR is advisory only — it is NOT a validated injury predictor in the
    research literature; treat the flag as a soft heuristic, not a verdict.
    """
    timeline = _continuous_daily_load(load_series)
    need = _ACWR_ACUTE_DAYS + _ACWR_ACUTE_DAYS * _ACWR_CHRONIC_WEEKS
    if len(timeline) < need:
        return {"availability": _accumulating(len(timeline), need)}

    loads = [v for _, v in timeline]
    acute = sum(loads[-7:])
    prior_weeks = [sum(loads[-7 * (w + 1) : -7 * w] if w else loads[-7:]) for w in range(1, 4)]
    chronic = sum(prior_weeks) / len(prior_weeks)
    if chronic <= 0:
        return {"availability": "ok", "acwr": None, "flag": "insufficient-chronic"}

    ratio = acute / chronic
    if ratio < 0.8:
        flag = "under"
    elif ratio >= 1.5:
        flag = "high"
    elif 0.8 <= ratio <= 1.3:
        flag = "sweet-spot"
    else:
        flag = "elevated"
    return {"availability": "ok", "acwr": round(ratio, 2), "flag": flag}


# ── Foster monotony & strain ─────────────────────────────────────────


def compute_monotony_strain(load_series: list[dict]) -> dict[str, Any]:
    """Foster training monotony (mean/SD) and strain (sum×monotony) over 7d.

    Zero-load days are included — that is the whole point: a 'samey' week with no
    rest scores high monotony, which correlates with maladaptation.
    """
    timeline = _continuous_daily_load(load_series)
    if len(timeline) < _MONOTONY_WINDOW_DAYS:
        return {"availability": _accumulating(len(timeline), _MONOTONY_WINDOW_DAYS)}

    window = [v for _, v in timeline[-_MONOTONY_WINDOW_DAYS:]]
    n = len(window)
    mean = sum(window) / n
    var = sum((x - mean) ** 2 for x in window) / n
    sd = math.sqrt(var)
    # sd==0 means perfectly identical days → maximal (infinite) monotony.
    monotony = (float("inf") if mean > 0 else 0.0) if sd == 0 else mean / sd
    strain = sum(window) * monotony
    return {
        "availability": "ok",
        "monotony": round(monotony, 2) if math.isfinite(monotony) else None,
        "strain": round(strain, 2) if math.isfinite(strain) else None,
        "concerning": monotony > 2,
    }


# ── Ramp rate (CTL today − CTL 7d ago) ───────────────────────────────


def compute_ramp_rate(ctl_block: dict) -> dict[str, Any]:
    series = ctl_block.get("series") if isinstance(ctl_block, dict) else None
    if not series or len(series) < 8:
        have = len(series) if series else 0
        return {"availability": _accumulating(have, 8)}
    ramp = series[-1]["ctl"] - series[-8]["ctl"]
    return {"availability": "ok", "ramp_rate": round(ramp, 2), "high": ramp > 8}


# ── Injury spike (acute distance jump vs prior 30d longest run) ──────


def _injury_tier(pct: float) -> str | None:
    if pct > 100:
        return "severe"
    if pct >= 30:
        return "high"
    if pct >= 10:
        return "moderate"
    return None


def compute_injury_spike(activities: list) -> dict[str, Any]:
    """Per run, distance vs the longest run in the prior 30 days → % jump."""
    runs = sorted(
        (
            a
            for a in activities
            if "run" in str(getattr(a, "activity_type", "")).lower()
            and (getattr(a, "distance_meters", 0) or 0) > 0
        ),
        key=lambda a: a.start_time,
    )
    if len(runs) < 2:
        return {"availability": _accumulating(len(runs), 2), "spikes": []}

    spikes = []
    lo = 0  # runs are sorted, so the 30-day window's left edge only moves forward
    for i, run in enumerate(runs):
        cutoff = run.start_time - timedelta(days=_INJURY_LOOKBACK_DAYS)
        while lo < i and runs[lo].start_time < cutoff:
            lo += 1
        if lo == i:
            continue
        longest = max(p.distance_meters for p in runs[lo:i])
        if longest <= 0:
            continue
        pct = (run.distance_meters - longest) / longest * 100
        tier = _injury_tier(pct)
        if tier:
            spikes.append(
                {
                    "activity_id": getattr(run, "activity_id", None),
                    "date": _activity_date(run),
                    "pct_jump": round(pct, 1),
                    "tier": tier,
                }
            )
    return {"availability": "ok", "spikes": spikes}


# ── Aerobic / anaerobic split (rolling 28d Training Effect) ──────────


def compute_aerobic_anaerobic_split(activities: list) -> dict[str, Any]:
    cutoff = None
    times = [getattr(a, "start_time", None) for a in activities]
    times = [t for t in times if isinstance(t, (datetime, date))]
    if times:
        latest = max(times)
        cutoff = latest - timedelta(days=_TE_WINDOW_DAYS)

    aero = anaero = 0.0
    counted = 0
    for a in activities:
        st = getattr(a, "start_time", None)
        if cutoff is not None and isinstance(st, (datetime, date)) and st < cutoff:
            continue
        te_a = getattr(a, "training_effect_aerobic", None)
        te_an = getattr(a, "training_effect_anaerobic", None)
        if te_a is None and te_an is None:
            continue
        aero += te_a or 0.0
        anaero += te_an or 0.0
        counted += 1

    if counted == 0:
        return {"availability": _accumulating(0, 1)}
    total = aero + anaero
    return {
        "availability": "ok",
        "aerobic": round(aero, 2),
        "anaerobic": round(anaero, 2),
        "ratio": round(aero / anaero, 2) if anaero > 0 else None,
        "aerobic_pct": round(aero / total * 100, 1) if total > 0 else None,
        "anaerobic_pct": round(anaero / total * 100, 1) if total > 0 else None,
    }


# ── History helpers ──────────────────────────────────────────────────


def _series(history: list, key: str) -> list[tuple[str, float]]:
    """Extract (date, value) pairs for a history key, skipping None."""
    out = []
    for row in history:
        v = row.get(key)
        if v is not None:
            out.append((row.get("date", ""), float(v)))
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


# ── HRV (lnRMSSD baseline, normal range, CV) ─────────────────────────


def compute_hrv(history: list) -> dict[str, Any]:
    """HRV trend from hrv_last_night (ms) → lnRMSSD.

    baseline = 7-day rolling mean of ln; normal_range = baseline ± 0.5·SD where
    SD is taken over ~60 days. status compares the latest ln against that band.
    """
    raw = _series(history, "hrv_last_night")
    if not raw:
        return {"availability": _accumulating(0, _HRV_BASELINE_DAYS), "status": "insufficient"}

    lns = [math.log(v) for _, v in raw if v > 0]
    if len(lns) < _HRV_BASELINE_DAYS:
        return {
            "availability": _accumulating(len(lns), _HRV_BASELINE_DAYS),
            "current_ln": round(lns[-1], 3) if lns else None,
            "status": "insufficient",
        }

    baseline = _mean(lns[-_HRV_BASELINE_DAYS:])
    ref = lns[-_HRV_REF_DAYS:]
    sd = _sd(ref)
    low, high = baseline - 0.5 * sd, baseline + 0.5 * sd
    mean7 = _mean(lns[-_HRV_BASELINE_DAYS:])
    sd7 = _sd(lns[-_HRV_BASELINE_DAYS:])
    cv = (sd7 / mean7 * 100) if mean7 else 0.0
    current = lns[-1]

    if current < low:
        status, rec = "below", "back-off — suppressed HRV signals incomplete recovery"
    elif current > high:
        status, rec = "above", "train-hard — HRV elevated, parasympathetic readiness high"
    else:
        status, rec = "within", "train-as-planned — HRV within normal range"

    return {
        "availability": "ok",
        "current_ln": round(current, 3),
        "baseline_ln": round(baseline, 3),
        "normal_range": [round(low, 3), round(high, 3)],
        "cv": round(cv, 2),
        "status": status,
        "recommendation": rec,
    }


# ── Resting HR trend ─────────────────────────────────────────────────


def compute_resting_hr_trend(history: list) -> dict[str, Any]:
    raw = _series(history, "resting_hr")
    if len(raw) < 2:
        return {"availability": _accumulating(len(raw), _RHR_BASELINE_DAYS)}
    vals = [v for _, v in raw]
    baseline = _mean(vals[-(_RHR_BASELINE_DAYS + 1) : -1]) or _mean(vals[:-1])
    latest = vals[-1]
    if baseline <= 0:
        return {"availability": "ok", "elevated": False}
    dev_bpm = latest - baseline
    dev_pct = dev_bpm / baseline * 100
    return {
        "availability": "ok",
        "baseline": round(baseline, 1),
        "latest": round(latest, 1),
        "deviation_bpm": round(dev_bpm, 1),
        "deviation_pct": round(dev_pct, 1),
        "elevated": dev_pct > 5,
    }


# ── Sleep ────────────────────────────────────────────────────────────


def compute_sleep(history: list) -> dict[str, Any]:
    if not history:
        return {"availability": _accumulating(0, 1)}
    latest = history[-1]
    score = latest.get("sleep_score")
    deep = latest.get("sleep_deep_seconds") or 0.0
    rem = latest.get("sleep_rem_seconds") or 0.0
    light = latest.get("sleep_light_seconds") or 0.0
    total = deep + rem + light

    architecture = None
    if total > 0:
        architecture = {
            "deep_pct": round(deep / total * 100, 1),
            "rem_pct": round(rem / total * 100, 1),
            "light_pct": round(light / total * 100, 1),
        }

    nights = _series(history, "sleep_duration_seconds")[-_SLEEP_DEBT_NIGHTS:]
    sleep_debt_hours = sum(max(0.0, _SLEEP_TARGET_SECONDS - v) for _, v in nights) / 3600.0

    scores = [v for _, v in _series(history, "sleep_score")]
    trend = "flat"
    if len(scores) >= 2:
        trend = "improving" if scores[-1] > scores[0] else "declining" if scores[-1] < scores[0] else "flat"

    # Last 14 nights of stage minutes for the stacked history panel.
    stages_14d = []
    for row in history[-14:]:
        d, r, li = (row.get("sleep_deep_seconds"), row.get("sleep_rem_seconds"),
                    row.get("sleep_light_seconds"))
        if not any((d, r, li)):
            continue
        stages_14d.append({
            "date": str(row.get("date")),
            "deep_min": round((d or 0) / 60),
            "rem_min": round((r or 0) / 60),
            "light_min": round((li or 0) / 60),
        })

    return {
        "availability": "ok",
        "score": score,
        "architecture": architecture,
        "sleep_debt_hours": round(sleep_debt_hours, 2),
        "trend": trend,
        "stages_14d": stages_14d,
    }


# ── Body battery & stress trends ─────────────────────────────────────


def _simple_trend(values: list[float]) -> str:
    if len(values) < 2:
        return "flat"
    if values[-1] > values[0]:
        return "rising"
    if values[-1] < values[0]:
        return "falling"
    return "flat"


def compute_body_battery_trend(history: list) -> dict[str, Any]:
    highs = [v for _, v in _series(history, "body_battery_high")]
    if not highs:
        return {"availability": _accumulating(0, 2)}
    return {
        "availability": "ok",
        "latest_high": highs[-1],
        "mean_high": round(_mean(highs), 1),
        "trend": _simple_trend(highs),
    }


def compute_stress_trend(history: list) -> dict[str, Any]:
    avgs = [v for _, v in _series(history, "stress_avg")]
    if not avgs:
        return {"availability": _accumulating(0, 2)}
    mean = _mean(avgs)
    return {
        "availability": "ok",
        "latest_avg": avgs[-1],
        "mean_avg": round(mean, 1),
        "trend": _simple_trend(avgs),
        "elevated": avgs[-1] > 50,
    }


# ── Overnight respiration & SpO2 (illness early-warning) ────────────


def compute_respiration_trend(history: list) -> dict[str, Any]:
    """Overnight respiration vs a rolling baseline — elevation precedes illness."""
    raw = _series(history, "respiration_avg_sleep")
    if len(raw) < 2:
        return {"availability": _accumulating(len(raw), _RESP_BASELINE_DAYS)}
    vals = [v for _, v in raw]
    baseline = _mean(vals[-(_RESP_BASELINE_DAYS + 1) : -1]) or _mean(vals[:-1])
    latest = vals[-1]
    dev = latest - baseline
    return {
        "availability": "ok",
        "baseline": round(baseline, 1),
        "latest": round(latest, 1),
        "deviation": round(dev, 1),
        "elevated": baseline > 0 and dev >= 1.5,
    }


def compute_spo2_trend(history: list) -> dict[str, Any]:
    """Overnight SpO2 vs baseline — absolute floor 94% or a ≥2-point drop."""
    raw = _series(history, "spo2_avg")
    if not raw:
        return {"availability": _accumulating(0, 1)}
    vals = [v for _, v in raw]
    latest = vals[-1]
    baseline = _mean(vals[-(_SPO2_BASELINE_DAYS + 1) : -1]) or latest
    return {
        "availability": "ok",
        "baseline": round(baseline, 1),
        "latest": round(latest, 1),
        "low": latest < 94 or (baseline - latest) >= 2,
    }


def compute_skin_temp(history: list) -> dict[str, Any]:
    """Overnight skin-temp deviation — Garmin reports it vs its own baseline, so
    no rolling window here; a sustained positive deviation precedes fever."""
    raw = _series(history, "skin_temp_deviation_c")
    if not raw:
        return {"availability": _accumulating(0, 1)}
    latest = raw[-1][1]
    return {
        "availability": "ok",
        "latest": round(latest, 2),
        "elevated": latest >= 1.0,
    }


def compute_illness_watch(resp: dict, spo2: dict, rhr: dict, hrv: dict,
                          skin_temp: dict | None = None) -> dict[str, Any]:
    """Illness early-warning distinct from overtraining.

    Fires only on systemic evidence (elevated overnight respiration, low SpO2,
    or raised skin temperature) — cardio-only patterns (RHR up, HRV down) belong
    to the overtraining composite. Corroboration by any second signal escalates
    watch → alert.
    """
    signals: list[str] = []
    if resp.get("elevated"):
        signals.append("respiration_elevated")
    if spo2.get("low"):
        signals.append("spo2_low")
    if (skin_temp or {}).get("elevated"):
        signals.append("skin_temp_elevated")
    respiratory = bool(signals)
    if rhr.get("elevated"):
        signals.append("rhr_elevated")
    if hrv.get("status") == "below":
        signals.append("hrv_below")
    if not respiratory:
        level = "none"
    elif len(signals) >= 2:
        level = "alert"
    else:
        level = "watch"
    return {"availability": "ok", "signals": signals, "level": level}


# ── Overtraining composite (count red flags) ─────────────────────────


def compute_overtraining_composite(
    history: list,
    hrv: dict,
    rhr: dict,
    sleep: dict,
    ctl: dict,
    monotony: dict,
    ramp: dict,
    stress: dict,
) -> dict[str, Any]:
    """Count overtraining red flags and bucket into green/caution/deload."""
    flags: list[str] = []

    # HRV below normal range for ≥3 of the last days.
    lns = [math.log(v) for _, v in _series(history, "hrv_last_night") if v > 0]
    if hrv.get("status") != "insufficient" and hrv.get("normal_range"):
        low = hrv["normal_range"][0]
        below_days = sum(1 for x in lns[-7:] if x < low)
        if below_days >= 3:
            flags.append("hrv_below_3d")

    if rhr.get("elevated"):
        flags.append("rhr_elevated")
    if sleep.get("trend") == "declining" or (sleep.get("sleep_debt_hours") or 0) > 8:
        flags.append("sleep_debt")
    if isinstance(ctl, dict) and ctl.get("tsb") is not None and ctl["tsb"] < -30:
        flags.append("tsb_high_fatigue")
    if monotony.get("concerning"):
        flags.append("monotony_high")
    if ramp.get("high"):
        flags.append("ramp_high")
    if stress.get("elevated"):
        flags.append("stress_elevated")

    n = len(flags)
    level = "green" if n <= 1 else "caution" if n <= 3 else "deload"
    return {"availability": "ok", "red_flags": flags, "count": n, "level": level}


# ── Readiness composite (weighted 0-100) ─────────────────────────────

_READINESS_WEIGHTS = {
    "hrv": 0.30,
    "sleep": 0.25,
    "tsb": 0.20,
    "body_battery": 0.10,
    "rhr": 0.10,
    "stress": 0.05,
}


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def compute_readiness_composite(
    hrv: dict, sleep: dict, ctl: dict, bb: dict, rhr: dict, stress: dict
) -> dict[str, Any]:
    """Weighted readiness 0-100 over whatever signals are available.

    Each sub-score is normalised to 0..1 (higher = readier), then weights are
    renormalised across only the present signals so a short history still yields
    a meaningful score rather than a deflated one.
    """
    sub: dict[str, float] = {}

    # HRV vs normal range: within → 1.0, below → low, above → high.
    if hrv.get("status") == "within":
        sub["hrv"] = 0.8
    elif hrv.get("status") == "above":
        sub["hrv"] = 1.0
    elif hrv.get("status") == "below":
        sub["hrv"] = 0.3

    # Sleep: blend score (0-100) with debt penalty.
    if sleep.get("availability") == "ok" and sleep.get("score") is not None:
        s = sleep["score"] / 100.0
        debt_penalty = _clamp01((sleep.get("sleep_debt_hours") or 0) / 16.0)
        sub["sleep"] = _clamp01(s - 0.5 * debt_penalty)

    # TSB: map −30..+25 onto 0..1 (more fatigue = less ready).
    if isinstance(ctl, dict) and ctl.get("tsb") is not None:
        sub["tsb"] = _clamp01((ctl["tsb"] + 30) / 55.0)

    if bb.get("availability") == "ok" and bb.get("latest_high") is not None:
        sub["body_battery"] = _clamp01(bb["latest_high"] / 100.0)

    # RHR inverted: elevation lowers readiness.
    if rhr.get("availability") == "ok" and rhr.get("deviation_pct") is not None:
        sub["rhr"] = _clamp01(1.0 - max(0.0, rhr["deviation_pct"]) / 10.0)

    # Stress inverted.
    if stress.get("availability") == "ok" and stress.get("latest_avg") is not None:
        sub["stress"] = _clamp01(1.0 - stress["latest_avg"] / 100.0)

    if not sub:
        return {"availability": _accumulating(0, 1), "score": None}

    total_w = sum(_READINESS_WEIGHTS[k] for k in sub)
    score = sum(sub[k] * _READINESS_WEIGHTS[k] for k in sub) / total_w * 100
    score = round(min(100.0, max(0.0, score)), 1)
    band = "green" if score > 70 else "moderate" if score >= 40 else "low"
    driver = min(sub, key=sub.get)  # weakest normalised signal drives the score down
    return {
        "availability": "ok",
        "score": score,
        "band": band,
        "dominant_driver": driver,
        "components": {k: round(v, 3) for k, v in sub.items()},
    }


# ── Garmin native passthrough ────────────────────────────────────────

_STATUS_LABELS = {
    "productive": "Building fitness effectively",
    "maintaining": "Holding current fitness",
    "peaking": "Race-ready, peak form",
    "overreaching": "Training load very high — recovery needed",
    "unproductive": "Load high but fitness flat — check recovery",
    "detraining": "Fitness declining from low load",
    "recovery": "Light load — recovering",
    "strained": "Acute load very high relative to fitness",
}

_READINESS_LABELS = [
    (75, "High — ready for a hard session"),
    (50, "Moderate — train as planned"),
    (25, "Low — keep it easy"),
    (0, "Very low — prioritise recovery"),
]


def compute_garmin_native(profile: Any) -> dict[str, Any]:
    status = getattr(profile, "training_status", None)
    readiness = getattr(profile, "training_readiness", None)
    readiness_label = None
    if readiness is not None:
        readiness_label = next(lbl for thr, lbl in _READINESS_LABELS if readiness >= thr)
    return {
        "availability": "ok",
        "training_status": status,
        "training_status_label": _STATUS_LABELS.get(str(status).lower()) if status else None,
        "load_focus": getattr(profile, "load_focus", None),
        "training_readiness": readiness,
        "training_readiness_label": readiness_label,
        "training_load_7day": getattr(profile, "training_load_7day", None),
        "running_tolerance": getattr(profile, "running_tolerance", None),
    }


# ── Entry point ──────────────────────────────────────────────────────


def compute_load_recovery(history: list, activities: list, profile,
                          rpe_map: dict | None = None,
                          bike_rides: list[dict] | None = None) -> dict:
    """Compute the full training-load / recovery / wellbeing report.

    Never raises on missing data. Each block carries an 'availability' tag of
    'ok' or {'status': 'accumulating', ...}. Returns a JSON-serialisable dict.
    """
    resting_hr = getattr(profile, "resting_hr", None) or 50
    max_hr = getattr(profile, "max_hr", None) or 190

    daily = compute_daily_load(activities, resting_hr, max_hr, rpe_map=rpe_map,
                               bike_rides=bike_rides)
    load_series = daily.get("series", [])

    ctl = compute_ctl_atl_tsb(load_series)
    acwr = compute_acwr(load_series)
    monotony = compute_monotony_strain(load_series)
    ramp = compute_ramp_rate(ctl)
    injury = compute_injury_spike(activities)
    te_split = compute_aerobic_anaerobic_split(activities)

    hrv = compute_hrv(history)
    rhr = compute_resting_hr_trend(history)
    sleep = compute_sleep(history)
    bb = compute_body_battery_trend(history)
    stress = compute_stress_trend(history)
    resp = compute_respiration_trend(history)
    spo2 = compute_spo2_trend(history)
    skin_temp = compute_skin_temp(history)
    illness = compute_illness_watch(resp, spo2, rhr, hrv, skin_temp)

    overtraining = compute_overtraining_composite(
        history, hrv, rhr, sleep, ctl, monotony, ramp, stress
    )
    readiness = compute_readiness_composite(hrv, sleep, ctl, bb, rhr, stress)
    garmin = compute_garmin_native(profile)

    return {
        "daily_load": daily,
        "ctl_atl_tsb": ctl,
        "acwr": acwr,
        "monotony_strain": monotony,
        "ramp_rate": ramp,
        "injury_spike": injury,
        "aerobic_anaerobic_split": te_split,
        "hrv": hrv,
        "resting_hr_trend": rhr,
        "sleep": sleep,
        "body_battery_trend": bb,
        "stress_trend": stress,
        "respiration_trend": resp,
        "spo2_trend": spo2,
        "skin_temp": skin_temp,
        "illness_watch": illness,
        "overtraining_composite": overtraining,
        "readiness_composite": readiness,
        "garmin_native": garmin,
    }
