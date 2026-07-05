"""Running-engine & durability metrics computed from activities + per-activity details.

All metrics degrade gracefully: when the required data is missing they return a
result carrying an ``available``/``confidence`` flag rather than raising. The public
entry point is :func:`compute_running_metrics`, returning a JSON-serializable dict.

Sports-science grounding (kept terse on purpose):
- Efficiency factor (EF) = speed / HR on easy runs tracks aerobic efficiency over time.
- Aerobic decoupling = drift in EF between first/second half of a steady run (Pfitzinger/Friel).
- Critical speed / critical power = asymptote of the distance-time (or work-time) line.
- HRR60 = heart-rate recovery 60s after peak; higher is fitter.
- 80/20 intensity distribution = polarized training adherence (Seiler).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

# ── small stdlib-only stats helpers ───────────────────────────────────


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float] | None:
    """Ordinary least squares. Returns (slope, intercept, r2) or None if degenerate."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:  # all x identical -> no slope defined
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    syy = sum((y - my) ** 2 for y in ys)
    if syy == 0:  # perfectly flat y -> treat as perfect fit
        r2 = 1.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r2 = 1.0 - ss_res / syy
    return slope, intercept, r2


def _is_run(activity_type: str | None) -> bool:
    return bool(activity_type) and "run" in activity_type.lower()


def _days_since(t0: datetime, t: datetime) -> float:
    return (t - t0).total_seconds() / 86400.0


# ── dataclasses (internal; asdict()'d on the way out) ──────────────────


@dataclass
class EfficiencyFactor:
    available: bool = False
    current: float | None = None
    trend_per_week: float | None = None
    n: int = 0
    series: list[dict] = field(default_factory=list)


@dataclass
class Decoupling:
    available: bool = False
    latest_pct: float | None = None
    average_pct: float | None = None
    grade: str | None = None
    n: int = 0
    per_run: list[dict] = field(default_factory=list)


@dataclass
class CompromisedRun:
    available: bool = False
    mean_fade_pct: float | None = None
    grade: str | None = None
    n: int = 0
    per_run: list[dict] = field(default_factory=list)


@dataclass
class CriticalSpeed:
    available: bool = False
    confidence: str = "low"
    cs_mps: float | None = None
    cs_pace_sec_per_km: float | None = None
    d_prime_m: float | None = None
    r2: float | None = None
    points: list[dict] = field(default_factory=list)
    # power variant (only when avg_power present on enough runs)
    cp_available: bool = False
    cp_watts: float | None = None
    w_prime_j: float | None = None
    cp_r2: float | None = None
    cp_points: list[dict] = field(default_factory=list)


@dataclass
class HeartRateRecovery:
    available: bool = False
    hrr60: float | None = None
    best_hrr60: float | None = None
    grade: str | None = None
    n: int = 0


@dataclass
class IntensityDistribution:
    available: bool = False
    low_pct: float | None = None
    mid_pct: float | None = None
    high_pct: float | None = None
    eighty_twenty_score: float | None = None
    adherence: str | None = None
    grade: str | None = None
    total_minutes: float | None = None


@dataclass
class Pacing:
    available: bool = False
    mean_ratio: float | None = None
    tendency: str | None = None
    per_run: list[dict] = field(default_factory=list)


@dataclass
class VVO2Max:
    available: bool = False
    vvo2max_mps: float | None = None
    pace_sec_per_km: float | None = None
    source: str | None = None


@dataclass
class EconomyMetric:
    available: bool = False
    current: float | None = None
    slope_per_sec_per_km: float | None = None
    grade: str | None = None
    n: int = 0


@dataclass
class EconomyVsPace:
    cadence: EconomyMetric = field(default_factory=EconomyMetric)
    ground_contact_time: EconomyMetric = field(default_factory=EconomyMetric)
    vertical_ratio: EconomyMetric = field(default_factory=EconomyMetric)


# ── helpers operating on the detail dicts ──────────────────────────────


def _series_of(details: dict, activity_id: int) -> list[dict]:
    d = details.get(activity_id) if details else None
    if not d:
        return []
    s = d.get("series")
    return s if isinstance(s, list) else []


def _splits_of(details: dict, activity_id: int) -> list[dict]:
    d = details.get(activity_id) if details else None
    if not d:
        return []
    s = d.get("splits")
    return s if isinstance(s, list) else []


def _hr_zones_of(details: dict, activity_id: int) -> list[dict]:
    d = details.get(activity_id) if details else None
    if not d:
        return []
    z = d.get("hr_zones")
    return z if isinstance(z, list) else []


# ── 1. efficiency factor ───────────────────────────────────────────────


def _efficiency_factor(runs: list, max_hr: int | None) -> EfficiencyFactor:
    if not max_hr:
        return EfficiencyFactor()
    easy_cap = 0.80 * max_hr
    pts: list[tuple[datetime, float]] = []
    for a in runs:
        if not a.avg_hr or a.avg_hr > easy_cap:
            continue
        if not a.duration_seconds or not a.distance_meters:
            continue
        speed_m_per_min = a.distance_meters / a.duration_seconds * 60.0
        ef = speed_m_per_min / a.avg_hr  # m/min per bpm
        pts.append((a.start_time, ef))
    if not pts:
        return EfficiencyFactor()
    pts.sort(key=lambda p: p[0])
    t0 = pts[0][0]
    series = [{"date": t.isoformat(), "ef": round(ef, 4)} for t, ef in pts]
    trend = None
    fit = _linreg([_days_since(t0, t) for t, _ in pts], [ef for _, ef in pts])
    if fit:
        trend = round(fit[0] * 7.0, 5)  # EF change per week
    return EfficiencyFactor(
        available=True,
        current=round(pts[-1][1], 4),
        trend_per_week=trend,
        n=len(pts),
        series=series,
    )


# ── 2. decoupling ──────────────────────────────────────────────────────


def _decoupling_grade(pct: float) -> str:
    if pct < 5:
        return "strong"
    if pct <= 10:
        return "moderate"
    return "weak"


def _decoupling(runs: list, details: dict) -> Decoupling:
    per_run: list[dict] = []
    for a in runs:
        if not a.duration_seconds or a.duration_seconds < 20 * 60:
            continue
        series = _series_of(details, a.activity_id)
        usable = [s for s in series if s.get("hr") and s.get("pace")]
        if len(usable) < 10:
            continue
        paces = [s["pace"] for s in usable]
        mp = _mean(paces)
        if not mp:
            continue
        # High pace variance => intervals/fartlek, skip (CV > 15%).
        var = sum((p - mp) ** 2 for p in paces) / len(paces)
        if (var ** 0.5) / mp > 0.15:
            continue
        warm = max(1, int(len(usable) * 0.05))  # drop ~5% warmup
        body = usable[warm:]
        if len(body) < 4:
            continue
        mid = len(body) // 2
        first, second = body[:mid], body[mid:]
        ef1 = _half_ef(first)
        ef2 = _half_ef(second)
        if ef1 is None or ef2 is None or ef1 == 0:
            continue
        pct = (ef1 - ef2) / ef1 * 100.0
        per_run.append(
            {
                "date": a.start_time.isoformat(),
                "pct": round(pct, 2),
                "duration_min": round(a.duration_seconds / 60.0, 1),
            }
        )
    if not per_run:
        return Decoupling()
    pcts = [r["pct"] for r in per_run]
    avg = _mean(pcts)
    latest = per_run[-1]["pct"]
    return Decoupling(
        available=True,
        latest_pct=round(latest, 2),
        average_pct=round(avg, 2),
        grade=_decoupling_grade(avg),
        n=len(per_run),
        per_run=per_run,
    )


def _half_ef(samples: list[dict]) -> float | None:
    """EF for a half = mean(speed)/mean(hr), speed = 1000/pace (m/s)."""
    speeds = [1000.0 / s["pace"] for s in samples if s.get("pace")]
    hrs = [s["hr"] for s in samples if s.get("hr")]
    ms = _mean(speeds)
    mh = _mean(hrs)
    if ms is None or mh is None or mh == 0:
        return None
    return ms / mh


# ── 3. compromised run (in-session fade) ───────────────────────────────


def _fade_grade(pct: float) -> str:
    if pct < 3:
        return "strong"
    if pct <= 7:
        return "moderate"
    return "weak"


def _compromised_run(runs: list, details: dict) -> CompromisedRun:
    per_run: list[dict] = []
    for a in runs:
        splits = [s for s in _splits_of(details, a.activity_id) if s.get("pace_sec")]
        if len(splits) < 4:
            continue
        q = max(1, len(splits) // 4)  # first/last 25%
        first = _mean([s["pace_sec"] for s in splits[:q]])
        last = _mean([s["pace_sec"] for s in splits[-q:]])
        if not first:
            continue
        fade = (last - first) / first * 100.0
        per_run.append({"date": a.start_time.isoformat(), "fade_pct": round(fade, 2)})
    if not per_run:
        return CompromisedRun()
    mean_fade = _mean([r["fade_pct"] for r in per_run])
    return CompromisedRun(
        available=True,
        mean_fade_pct=round(mean_fade, 2),
        grade=_fade_grade(mean_fade),
        n=len(per_run),
        per_run=per_run,
    )


# ── 4. critical speed / critical power ─────────────────────────────────

# Target durations (s) for best-effort extraction.
_CS_TARGETS = (180, 360, 720, 1200)


def _best_efforts_distance(runs: list, details: dict) -> list[tuple[float, float]]:
    """Best (time_s, distance_m) the athlete sustained near each target duration.

    Derived from cumulative per-km split distance/time, falling back to the
    activity total when splits are absent.
    """
    best: dict[int, tuple[float, float]] = {}
    for a in runs:
        windows = _effort_windows(a, details)
        for target in _CS_TARGETS:
            chosen = _closest_window(windows, target)
            if chosen is None:
                continue
            t_s, dist = chosen
            # Keep the effort whose distance/time ratio (speed) is fastest.
            prev = best.get(target)
            if prev is None or dist / t_s > prev[1] / prev[0]:
                best[target] = (t_s, dist)
    return list(best.values())


def _effort_windows(a, details: dict) -> list[tuple[float, float]]:
    """Cumulative (time_s, distance_m) prefixes from splits, plus the activity total."""
    out: list[tuple[float, float]] = []
    cum_t = cum_d = 0.0
    for s in _splits_of(details, a.activity_id):
        dur = s.get("duration_s")
        dist = s.get("distance_m")
        if not dur or not dist:
            continue
        cum_t += dur
        cum_d += dist
        out.append((cum_t, cum_d))
    if a.duration_seconds and a.distance_meters:
        out.append((float(a.duration_seconds), float(a.distance_meters)))
    return out


def _closest_window(
    windows: list[tuple[float, float]], target: float
) -> tuple[float, float] | None:
    """Pick the cumulative window whose time is closest to *target* (within 40%)."""
    best = None
    best_err = None
    for t_s, dist in windows:
        err = abs(t_s - target) / target
        if err > 0.40:
            continue
        if best_err is None or err < best_err:
            best, best_err = (t_s, dist), err
    return best


def _power_points(runs: list) -> list[tuple[float, float]]:
    """(time_s, work_j) per run with avg_power, for the CP/W' regression."""
    pts: list[tuple[float, float]] = []
    for a in runs:
        if not a.avg_power or not a.duration_seconds:
            continue
        pts.append((float(a.duration_seconds), a.avg_power * a.duration_seconds))
    return pts


def _critical_speed(runs: list, details: dict) -> CriticalSpeed:
    out = CriticalSpeed()
    pts = _best_efforts_distance(runs, details)
    # Need >=3 points spanning a real duration range.
    ts = [t for t, _ in pts]
    if len(pts) >= 3 and (max(ts) - min(ts)) > 0:
        fit = _linreg(ts, [d for _, d in pts])  # distance = CS*t + D'
        if fit:
            cs, dprime, r2 = fit
            if cs > 0:
                out.available = True
                out.cs_mps = round(cs, 4)
                out.cs_pace_sec_per_km = round(1000.0 / cs, 1)
                out.d_prime_m = round(dprime, 1)
                out.r2 = round(r2, 4)
                out.confidence = "high" if r2 > 0.9 else "low"
                out.points = [{"t_s": round(t, 1), "dist_m": round(d, 1)} for t, d in pts]

    ppts = _power_points(runs)
    pts_s = [t for t, _ in ppts]
    if len(ppts) >= 3 and (max(pts_s) - min(pts_s)) > 0:
        fit = _linreg(pts_s, [w for _, w in ppts])  # work = CP*t + W'
        if fit:
            cp, wprime, r2 = fit
            if cp > 0:
                out.cp_available = True
                out.cp_watts = round(cp, 1)
                out.w_prime_j = round(wprime, 1)
                out.cp_r2 = round(r2, 4)
                out.cp_points = [{"t_s": round(t, 1), "work_j": round(w, 1)} for t, w in ppts]
    return out


# ── 5. heart-rate recovery ─────────────────────────────────────────────


def _hrr_grade(v: float) -> str:
    if v > 30:
        return "strong"
    if v >= 20:
        return "moderate"
    return "low"


def _hrr(runs: list, details: dict) -> HeartRateRecovery:
    values: list[float] = []
    for a in runs:
        series = [s for s in _series_of(details, a.activity_id) if s.get("hr") and s.get("t") is not None]
        if len(series) < 3:
            continue
        peak_i = max(range(len(series)), key=lambda i: series[i]["hr"])
        peak_t = series[peak_i]["t"]
        peak_hr = series[peak_i]["hr"]
        # Nearest sample to ~60s after the peak (must actually be later).
        later = [s for s in series if s["t"] > peak_t]
        if not later:
            continue
        target = peak_t + 60
        nearest = min(later, key=lambda s: abs(s["t"] - target))
        hrr = peak_hr - nearest["hr"]
        if hrr >= 0:
            values.append(float(hrr))
    if not values:
        return HeartRateRecovery()
    latest = values[-1]
    best = max(values)
    return HeartRateRecovery(
        available=True,
        hrr60=round(latest, 1),
        best_hrr60=round(best, 1),
        grade=_hrr_grade(best),
        n=len(values),
    )


# ── 6. intensity distribution (80/20) ──────────────────────────────────


def _intensity_distribution(runs: list, details: dict, now: datetime) -> IntensityDistribution:
    cutoff = now - timedelta(days=28)
    low = mid = high = 0.0  # Z1-2, Z3, Z4-5 seconds
    for a in runs:
        if a.start_time < cutoff:
            continue
        for z in _hr_zones_of(details, a.activity_id):
            zone = z.get("zone")
            secs = z.get("secs") or 0.0
            if zone in (1, 2):
                low += secs
            elif zone == 3:
                mid += secs
            elif zone in (4, 5):
                high += secs
    total = low + mid + high
    if total <= 0:
        return IntensityDistribution()
    low_pct = low / total * 100.0
    mid_pct = mid / total * 100.0
    high_pct = high / total * 100.0
    # Closeness to the polarized ideal: ~80% low, minimal Z3.
    score = max(0.0, 100.0 - abs(low_pct - 80.0) - mid_pct)
    if score >= 85:
        grade = "polarized"
    elif score >= 70:
        grade = "acceptable"
    else:
        grade = "too_much_mid"
    return IntensityDistribution(
        available=True,
        low_pct=round(low_pct, 1),
        mid_pct=round(mid_pct, 1),
        high_pct=round(high_pct, 1),
        eighty_twenty_score=round(score, 1),
        adherence="on_target" if low_pct >= 75 else "too_hard",
        grade=grade,
        total_minutes=round(total / 60.0, 1),
    )


# ── 7. pacing (negative split tendency) ────────────────────────────────


def _pacing(runs: list, details: dict) -> Pacing:
    per_run: list[dict] = []
    for a in runs:
        splits = [s for s in _splits_of(details, a.activity_id) if s.get("pace_sec")]
        if len(splits) < 2:
            continue
        mid = len(splits) // 2
        first = _mean([s["pace_sec"] for s in splits[:mid]])
        second = _mean([s["pace_sec"] for s in splits[mid:]])
        if not first:
            continue
        ratio = second / first
        per_run.append({"date": a.start_time.isoformat(), "ratio": round(ratio, 3)})
    if not per_run:
        return Pacing()
    mean_ratio = _mean([r["ratio"] for r in per_run])
    if mean_ratio < 0.98:
        tendency = "negative"
    elif mean_ratio <= 1.02:
        tendency = "even"
    else:
        tendency = "positive"
    return Pacing(
        available=True,
        mean_ratio=round(mean_ratio, 3),
        tendency=tendency,
        per_run=per_run,
    )


# ── 8. vVO2max ─────────────────────────────────────────────────────────


def _vvo2max(runs: list, profile) -> VVO2Max:
    max_hr = getattr(profile, "max_hr", None)
    # Prefer a measured near-maximal sustained effort (~5-6 min, HR >= 0.95*max).
    if max_hr:
        cap = 0.95 * max_hr
        best_speed = None
        for a in runs:
            if not a.avg_hr or a.avg_hr < cap:
                continue
            if not a.duration_seconds or not a.distance_meters:
                continue
            if not (4 * 60 <= a.duration_seconds <= 8 * 60):
                continue
            speed = a.distance_meters / a.duration_seconds
            if best_speed is None or speed > best_speed:
                best_speed = speed
        if best_speed:
            return VVO2Max(
                available=True,
                vvo2max_mps=round(best_speed, 3),
                pace_sec_per_km=round(1000.0 / best_speed, 1),
                source="measured",
            )
    # Fallback: vVO2max ~ 1.12 * lactate-threshold speed.
    lt = getattr(profile, "lactate_threshold_speed", None)
    if lt:
        speed = lt * 1.12
        return VVO2Max(
            available=True,
            vvo2max_mps=round(speed, 3),
            pace_sec_per_km=round(1000.0 / speed, 1),
            source="estimated_from_lt",
        )
    return VVO2Max()


# ── 9. economy vs pace ─────────────────────────────────────────────────


def _economy_metric(
    runs: list, attr: str, grade_fn
) -> EconomyMetric:
    pts: list[tuple[float, float]] = []  # (pace, value)
    for a in runs:
        pace = a.avg_pace_sec_per_km
        val = getattr(a, attr, None)
        if pace and val:
            pts.append((pace, val))
    if not pts:
        return EconomyMetric()
    current = pts[-1][1]
    slope = None
    fit = _linreg([p for p, _ in pts], [v for _, v in pts])
    if fit:
        slope = round(fit[0], 5)
    return EconomyMetric(
        available=True,
        current=round(current, 2),
        slope_per_sec_per_km=slope,
        grade=grade_fn(current),
        n=len(pts),
    )


def _cadence_grade(v: float) -> str:
    return "ok" if 165 <= v <= 180 else "off"


def _gct_grade(v: float) -> str:
    return "good" if v < 300 else "high"


def _vertical_ratio_grade(v: float) -> str:
    return "good" if v < 7 else "high"


def _economy_vs_pace(runs: list) -> EconomyVsPace:
    return EconomyVsPace(
        cadence=_economy_metric(runs, "avg_running_cadence", _cadence_grade),
        ground_contact_time=_economy_metric(runs, "avg_ground_contact_time", _gct_grade),
        vertical_ratio=_economy_metric(runs, "avg_vertical_ratio", _vertical_ratio_grade),
    )


# ── public entry point ─────────────────────────────────────────────────


def compute_effective_vo2max(activities: list, details: dict, profile) -> dict[str, Any]:
    """Runalyze-style effective VO2max per run: what fitness does each ordinary
    run imply, given the pace it produced at the HR it cost?

    VO2 at velocity from Daniels & Gilbert; %VO2max from %HRmax via the Swain
    relation (%VO2max ≈ (%HRmax − 37) / 63). Blends true VO2max with running
    economy — which is exactly why its TREND is the useful signal. Hot-day runs
    are conditions-adjusted first so summer doesn't read as detraining.
    """
    from paceforge.engine.enviro import adjusted_pace

    max_hr = getattr(profile, "max_hr", None)
    if not max_hr:
        return {"available": False, "note": "no max HR on profile"}

    points: list[dict] = []
    for a in activities or []:
        if not _is_run(getattr(a, "activity_type", None)):
            continue
        pace = getattr(a, "avg_pace_sec_per_km", None)
        hr = getattr(a, "avg_hr", None)
        dur = getattr(a, "duration_seconds", None) or 0
        st = getattr(a, "start_time", None)
        if not (pace and hr and st) or dur < 20 * 60 or not (180 < pace < 600):
            continue
        pct_hrmax = hr / max_hr
        pct_vo2 = (pct_hrmax * 100 - 37) / 63
        if pct_vo2 < 0.4:  # too easy to say anything about the ceiling
            continue
        detail = (details or {}).get(getattr(a, "activity_id", None)) or {}
        pace = adjusted_pace(pace, detail.get("weather")) or pace
        v = 60_000 / pace  # m/min
        vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
        eff = vo2 / pct_vo2
        if 25 < eff < 90:
            points.append({"date": str(st)[:10], "t": st, "effective_vo2max": round(eff, 1)})

    if len(points) < 3:
        return {"available": False, "note": f"only {len(points)} usable runs"}

    points.sort(key=lambda p: p["t"])
    # The HR→%VO2max inversion systematically overshoots (Runalyze solves the
    # same problem with a per-athlete correction factor); calibrate the LEVEL
    # to Garmin's lab-grade estimate and keep the per-run TREND, which is the
    # signal this metric exists for.
    raw_mean = sum(p["effective_vo2max"] for p in points) / len(points)
    garmin_vo2 = getattr(profile, "vo2_max", None)
    correction = (garmin_vo2 / raw_mean) if garmin_vo2 and raw_mean > 0 else 1.0
    for p in points:
        p["effective_vo2max"] = round(p["effective_vo2max"] * correction, 1)
    # 42-day EWMA over the run series (same time constant as CTL — fitness-speed).
    ewma = None
    for p in points:
        ewma = p["effective_vo2max"] if ewma is None else \
            ewma + (p["effective_vo2max"] - ewma) * (1 - 2.718281828 ** (-1 / 42))
        p["ewma"] = round(ewma, 1)
    t0, t1 = points[0]["t"], points[-1]["t"]
    weeks = max(_days_since(t0, t1) / 7.0, 0.1)
    xs = [_days_since(t0, p["t"]) / 7.0 for p in points]
    reg = _linreg(xs, [p["effective_vo2max"] for p in points])
    series = [{"date": p["date"], "value": p["effective_vo2max"], "ewma": p["ewma"]}
              for p in points]
    return {
        "available": True,
        "current": points[-1]["ewma"],
        "trend_per_week": round(reg[0], 2) if reg else None,
        "n": len(points),
        "window_weeks": round(weeks, 1),
        "calibrated_to_garmin": correction != 1.0,
        "correction_factor": round(correction, 3),
        "series": series[-60:],
    }


def compute_running_metrics(activities: list, details: dict, profile) -> dict[str, Any]:
    """Compute running-engine & durability metrics. Never raises on missing data."""
    details = details or {}
    runs = [a for a in (activities or []) if _is_run(getattr(a, "activity_type", None))]
    max_hr = getattr(profile, "max_hr", None)

    # "now" anchors the 28-day intensity window to the latest run (tests are deterministic).
    now = max((a.start_time for a in runs), default=datetime.now())

    ef = _efficiency_factor(runs, max_hr)
    decoupling = _decoupling(runs, details)
    compromised = _compromised_run(runs, details)
    cs = _critical_speed(runs, details)
    hrr = _hrr(runs, details)
    intensity = _intensity_distribution(runs, details, now)
    pacing = _pacing(runs, details)
    vvo2 = _vvo2max(runs, profile)
    economy = _economy_vs_pace(runs)
    eff_vo2 = compute_effective_vo2max(activities, details, profile)

    ef_direction = None
    if ef.available and ef.trend_per_week is not None:
        if ef.trend_per_week > 0:
            ef_direction = "improving"
        elif ef.trend_per_week < 0:
            ef_direction = "declining"
        else:
            ef_direction = "flat"

    headline = {
        "decoupling_grade": decoupling.grade,
        "compromised_fade_pct": compromised.mean_fade_pct,
        "ef_trend_direction": ef_direction,
        "critical_speed_pace_sec_per_km": cs.cs_pace_sec_per_km,
    }

    return {
        "efficiency_factor": asdict(ef),
        "decoupling": asdict(decoupling),
        "compromised_run": asdict(compromised),
        "critical_speed": asdict(cs),
        "hrr": asdict(hrr),
        "intensity_distribution": asdict(intensity),
        "pacing": asdict(pacing),
        "vvo2max": asdict(vvo2),
        "economy_vs_pace": asdict(economy),
        "effective_vo2max": eff_vo2,
        "headline": headline,
    }
