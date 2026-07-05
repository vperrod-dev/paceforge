"""Mean-maximal pace curves (intervals.icu-style) from stored activity series.

For every duration on a grid (30s … 60min) find the best average pace the athlete
has held for at least that long — overall for the recent window, per season for
year-over-year overlay, and "fatigued" (windows starting late in a session) as
the compromised-running picture: how much speed survives once the legs are loaded.
"""

from __future__ import annotations

from datetime import date, timedelta

# Best-effort durations (seconds). Sparse on purpose — the series are ~120-point
# downsamples, so sub-30s efforts aren't resolvable.
DURATION_GRID = (30, 60, 120, 300, 600, 1200, 2400, 3600)

# A window only counts as "fatigued" when it starts this deep into the session.
# Cheap, honest proxy for accumulated in-session work (matches the back half of
# a brick / simulation, where compromised running actually happens).
_FATIGUE_ONSET_SECONDS = 25 * 60

_RUN_TYPES = {"running", "treadmill_running", "track_running", "trail_running"}
_RECENT_DAYS = 90


def _series_points(detail: dict) -> list[tuple[float, float]]:
    """(t_seconds, speed_m_s) samples from a stored detail's series."""
    out = []
    for p in detail.get("series") or []:
        t, pace = p.get("t"), p.get("pace")
        if t is None or not pace or pace <= 0:
            continue
        out.append((float(t), 1000.0 / float(pace)))
    return out


def _best_speed(points: list[tuple[float, float]], duration: float,
                min_start: float = 0.0) -> float | None:
    """Best average speed over any window of at least `duration` seconds,
    considering only windows that start at/after `min_start`."""
    pts = [p for p in points if p[0] >= min_start]
    if len(pts) < 2:
        return None
    # Cumulative distance via stepwise integration between samples.
    times = [p[0] for p in pts]
    dist = [0.0]
    for i in range(1, len(pts)):
        dt = times[i] - times[i - 1]
        dist.append(dist[-1] + max(dt, 0) * pts[i - 1][1])
    if times[-1] - times[0] < duration:
        return None
    best = None
    j = 0
    for i in range(len(pts)):
        while j < len(pts) - 1 and times[j] - times[i] < duration:
            j += 1
        span = times[j] - times[i]
        if span >= duration:
            speed = (dist[j] - dist[i]) / span
            if best is None or speed > best:
                best = speed
    return best


def _curve(details: list[dict], min_start: float = 0.0) -> dict[int, float]:
    """{duration: best pace (sec/km)} across a set of activity details."""
    out: dict[int, float] = {}
    for d in details:
        points = _series_points(d)
        for dur in DURATION_GRID:
            speed = _best_speed(points, dur, min_start=min_start)
            if speed and speed > 0.5:  # ignore walking-pace noise
                pace = 1000.0 / speed
                if dur not in out or pace < out[dur]:
                    out[dur] = round(pace, 1)
    return out


def _activity_date(act) -> date | None:
    st = getattr(act, "start_time", None)
    if st is None:
        return None
    if hasattr(st, "date") and callable(st.date):
        return st.date()
    try:
        return date.fromisoformat(str(st)[:10])
    except ValueError:
        return None


def compute_pace_curves(activities: list, details: dict, today: date | None = None) -> dict:
    """Pace-duration curves: recent window, per-season overlay, and fatigued.

    `details` is {activity_id: detail} as returned by store.load_all_details().
    """
    today = today or date.today()
    run_details_by_date: list[tuple[date, dict]] = []
    for act in activities:
        if (getattr(act, "activity_type", "") or "").lower() not in _RUN_TYPES:
            continue
        d = details.get(getattr(act, "activity_id", None))
        ad = _activity_date(act)
        if d and ad and d.get("series"):
            run_details_by_date.append((ad, d))

    if not run_details_by_date:
        return {"available": False, "note": "no run time-series stored yet"}

    recent = [d for ad, d in run_details_by_date if ad >= today - timedelta(days=_RECENT_DAYS)]
    seasons: dict[str, list[dict]] = {}
    for ad, d in run_details_by_date:
        seasons.setdefault(str(ad.year), []).append(d)

    fresh = _curve(recent)
    fatigued = _curve(recent, min_start=_FATIGUE_ONSET_SECONDS)
    # Fatigue cost per duration: % pace lost once the session is >25 min old.
    fatigue_cost = {
        dur: round(100 * (fatigued[dur] - fresh[dur]) / fresh[dur], 1)
        for dur in fresh
        if dur in fatigued and fresh[dur] > 0
    }
    return {
        "available": bool(fresh),
        "durations": list(DURATION_GRID),
        "recent_90d": fresh,
        "fatigued_90d": fatigued,
        "fatigue_cost_pct": fatigue_cost,
        "seasons": {yr: _curve(ds) for yr, ds in sorted(seasons.items())},
        "fatigue_onset_min": _FATIGUE_ONSET_SECONDS // 60,
        "runs_used": len(recent),
    }
