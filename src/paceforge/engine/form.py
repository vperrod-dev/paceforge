"""Running-form trends + effort-recovery heart rate.

Form (cadence / stride / ground-contact / vertical ratio) is where this
athlete's stated weakness lives — the watch records it every run, this module
turns it into trend series the portal charts and the coach reads. Recovery HR
(how far HR falls in the 60s after an effort) is one of the strongest simple
fitness markers; it is mined from the per-activity HR time-series, so classes
and intervals both feed it.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from paceforge import store

_RUN_TYPES = {"running", "treadmill_running", "trail_running", "track_running",
              "indoor_running", "virtual_run"}

_LOOKBACK_DAYS = 90

# An HRR event needs a real effort (peak above this) and a real drop.
_MIN_PEAK_HR = 130
_MIN_DROP = 8


def _cadence_target() -> tuple[float, float]:
    try:
        t = json.loads((store.DATA_DIR / "watch-targets.json").read_text())
        return float(t["cadence_lo"]), float(t["cadence_hi"])
    except Exception:
        return 168.0, 172.0


def _when(a) -> date | None:
    st = getattr(a, "start_time", None)
    if isinstance(st, datetime):
        return st.date()
    try:
        return date.fromisoformat(str(st)[:10])
    except Exception:
        return None


def compute_form(activities: list, details: dict | None = None) -> dict:
    """Per-run form series + current/trend summaries + recovery-HR series."""
    lo, hi = _cadence_target()
    cutoff = date.today() - timedelta(days=_LOOKBACK_DAYS)

    series = []
    for a in activities:
        d = _when(a)
        if d is None or d < cutoff:
            continue
        if str(getattr(a, "activity_type", "")).lower() not in _RUN_TYPES:
            continue
        cad = getattr(a, "avg_running_cadence", None)
        if not cad:
            continue
        cad = float(cad)
        if cad < 120:   # strides/min firmware value — normalize to steps/min
            cad *= 2
        series.append({
            "date": d.isoformat(),
            "activity_id": getattr(a, "activity_id", None),
            "cadence": round(cad, 1),
            "stride_m": round(getattr(a, "avg_stride_length", 0) / 100, 2)
            if getattr(a, "avg_stride_length", None) else None,
            "gct_ms": round(getattr(a, "avg_ground_contact_time", 0))
            if getattr(a, "avg_ground_contact_time", None) else None,
            "vert_ratio": round(getattr(a, "avg_vertical_ratio", 0), 2)
            if getattr(a, "avg_vertical_ratio", None) else None,
            "pace_sec_km": getattr(a, "avg_pace_sec_per_km", None),
        })
    series.sort(key=lambda x: x["date"])

    def _avg(key, rows):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    recent = series[-3:]
    prior = [r for r in series
             if r["date"] <= (date.today() - timedelta(days=28)).isoformat()][-3:]

    def _trend(key):
        cur, old = _avg(key, recent), _avg(key, prior)
        return round(cur - old, 1) if cur is not None and old is not None else None

    return {
        "available": bool(series),
        "series": series,
        "cadence": {
            "current": _avg("cadence", recent),
            "target_lo": lo, "target_hi": hi,
            "trend_28d": _trend("cadence"),
        },
        "gct_ms": {"current": _avg("gct_ms", recent), "trend_28d": _trend("gct_ms")},
        "vert_ratio": {"current": _avg("vert_ratio", recent),
                       "trend_28d": _trend("vert_ratio")},
        "stride_m": {"current": _avg("stride_m", recent)},
        "recovery_hr": compute_recovery_hr(activities, details or {}),
    }


def _hrr_events(hr_points: list[tuple[float, float]]) -> list[int]:
    """60-second HR drops after efforts, from a sparse (t_sec, hr) series."""
    events = []
    n = len(hr_points)
    for i in range(1, n - 1):
        t, hr = hr_points[i]
        if hr < _MIN_PEAK_HR:
            continue
        # local peak: not exceeded by immediate neighbours
        if hr < hr_points[i - 1][1] or (i + 1 < n and hr < hr_points[i + 1][1]):
            continue
        # HR ~60s later (first sample at/after t+60, linear enough at 15s res)
        later = next((p for p in hr_points[i + 1:] if p[0] >= t + 55), None)
        if later is None or later[0] > t + 90:
            continue
        drop = int(hr - later[1])
        if drop >= _MIN_DROP:
            events.append(drop)
    return events


def compute_recovery_hr(activities: list, details: dict) -> dict:
    """Per-session recovery-HR series: best + median 60s drop, newest last.

    Every activity with an HR time-series counts — classes and intervals are
    exactly where the effort/recovery pattern lives.
    """
    cutoff = date.today() - timedelta(days=_LOOKBACK_DAYS)
    out = []
    for a in activities:
        d = _when(a)
        if d is None or d < cutoff:
            continue
        det = details.get(getattr(a, "activity_id", None))
        if det is None:
            continue
        pts = [(float(p.get("t", 0)), float(p["hr"]))
               for p in (det.get("series") or []) if p.get("hr")]
        if len(pts) < 8:
            continue
        events = _hrr_events(pts)
        if not events:
            continue
        events.sort()
        out.append({
            "date": d.isoformat(),
            "activity_id": getattr(a, "activity_id", None),
            "hrr60_best": events[-1],
            "hrr60_median": events[len(events) // 2],
            "n_efforts": len(events),
        })
    out.sort(key=lambda x: x["date"])

    recent = [s["hrr60_best"] for s in out[-5:]]
    prior = [s["hrr60_best"] for s in out
             if s["date"] <= (date.today() - timedelta(days=28)).isoformat()][-5:]
    cur = round(sum(recent) / len(recent), 1) if recent else None
    old = round(sum(prior) / len(prior), 1) if prior else None
    return {
        "available": bool(out),
        "series": out,
        "current_best_avg": cur,
        "trend_28d": round(cur - old, 1) if cur is not None and old is not None else None,
    }
