"""Limiter-ranking engine — turns the running/load/strength metric dicts into a
short, prioritized "what's holding you back + what to do" list, and the structured
object the LLM coach consumes.

Deterministic math stays here; the coach skill writes narrative from `coach_input`.
Rules are readiness-gated: when recovery signals are red, recovery becomes the
top limiter regardless of fitness gaps. We surface at most 3 (more reads as noise).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Limiter:
    name: str
    area: str            # endurance | durability | economy | speed | strength | pacing | recovery | distribution
    severity: float      # 0..1
    time_impact: float   # relative weight on HYROX result (stations+runs dominate)
    evidence: str        # the metric reading that fired this
    recommendation: str  # concrete action


def _g(d, *keys, default=None):
    """Nested get that tolerates missing/None blocks."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _available(block) -> bool:
    av = _g(block or {}, "available")
    if av is True:
        return True
    return _g(block or {}, "availability") == "ok"


def rank_limiters(running: dict, load: dict, strength: dict, *, goal: str = "HYROX",
                  profile_vo2max: float | None = None) -> dict:
    """Score candidate limiters, readiness-gate, return top-3 + the coach contract."""
    running, load, strength = running or {}, load or {}, strength or {}
    cands: list[Limiter] = []

    # --- Readiness gate (overrides fitness gaps for THIS week) ---
    ot = load.get("overtraining_composite") or {}
    rd = load.get("readiness_composite") or {}
    ot_level = ot.get("level")
    if ot_level == "deload" or rd.get("band") == "low":
        cands.append(Limiter(
            "Recovery first", "recovery", 1.0, 10.0,
            f"readiness {rd.get('score')} ({rd.get('band')}), overtraining {ot_level or 'flag'}",
            "Replace the next hard session with easy/rest until HRV and sleep recover. "
            "Fitness gaps wait; under-recovery is the limiter today."))

    # --- Durability / endurance ---
    dec = running.get("decoupling") or {}
    if _available(dec) and (dec.get("average_pct") or 0) > 8:
        cands.append(Limiter(
            "Aerobic durability", "durability", min((dec["average_pct"]) / 20, 1.0), 8.0,
            f"aerobic decoupling {dec.get('average_pct')}% (>8% = base fades within long efforts)",
            "Add a weekly progressive long run capped at zone-2 / decoupling <8%, +10%/wk for 4 weeks."))

    comp_race = strength.get("compromised_run_race") or {}
    comp_sess = running.get("compromised_run") or {}
    fade = comp_race.get("fade_pct") if _available(comp_race) else comp_sess.get("mean_fade_pct")
    if fade is not None and fade > 12:
        cands.append(Limiter(
            "Compromised running", "durability", min(fade / 30, 1.0), 9.0,
            f"run-fade {round(fade, 1)}% under fatigue (>12% = pace collapses late)",
            "Brick / compromised-run sessions: 6–8 × (1 station effort + 1 km at goal pace)."))

    # --- Training distribution (highest-ROI behavioural fix) ---
    idist = running.get("intensity_distribution") or {}
    if _available(idist) and idist.get("adherence") == "too_hard":
        cands.append(Limiter(
            "Grey-zone training", "distribution", 0.7, 7.0,
            f"only {idist.get('low_pct')}% easy / {idist.get('mid_pct')}% moderate "
            "(target ~80% easy, minimal zone-3)",
            "Slow easy days (cap HR at zone-2 ceiling) and concentrate hard work into fewer, harder sessions."))

    # --- VO2 / speed stimulus ---
    vo2_trend = _g(running, "efficiency_factor", "trend_per_week")
    aa = load.get("aerobic_anaerobic_split") or {}
    if _available(aa) and (aa.get("anaerobic_pct") or 0) < 12:
        cands.append(Limiter(
            "Anaerobic stimulus", "speed", 0.5, 5.0,
            f"only {aa.get('anaerobic_pct')}% of recent load is anaerobic (sleds/surges under-trained)",
            "Add one weekly VO2/anaerobic session (e.g. 5×3 min hard, or sled-style intervals)."))

    # --- Economy / mechanics ---
    econ = running.get("economy_vs_pace") or {}
    gct = econ.get("ground_contact_time") or {}
    cad = econ.get("cadence") or {}
    if _available(gct) and gct.get("grade") in ("needs_work", "high") or \
       (_available(cad) and cad.get("grade") in ("low", "needs_work")):
        cands.append(Limiter(
            "Running economy", "economy", 0.45, 6.0,
            f"economy flags (GCT {gct.get('current')}ms, cadence {cad.get('current')}spm)",
            "2–3×/wk heavy strength (≤4RM) + plyometrics for 8–12 weeks; cadence drills if over-striding."))

    # --- Strength / stations ---
    sp = strength.get("station_percentiles") or {}
    if _available(sp):
        weakest = sp.get("weakest") or sp.get("weakest_3") or []
        if weakest:
            names = ", ".join(str(w) for w in weakest[:3]).replace("_", " ")
            cands.append(Limiter(
                "Weak HYROX stations", "strength", 0.6, 8.0,
                f"slowest stations vs the field: {names}",
                f"Targeted volume 2×/wk on your 2–3 weakest stations ({names}); don't train all 8 equally."))

    hb = strength.get("hybrid_balance") or {}
    if hb.get("lagging_side") == "strength" and hb.get("confidence") in ("medium", "high"):
        cands.append(Limiter(
            "Run-dominant imbalance", "strength", 0.5, 6.0,
            f"run index {hb.get('run_index')} vs strength {hb.get('strength_index')} — strength lags",
            "2 strength days/wk (heavy + station volume); keep runs at maintenance to protect the gain."))

    # --- Pacing ---
    pac = running.get("pacing") or {}
    if _available(pac) and pac.get("tendency") == "positive":
        cands.append(Limiter(
            "Pacing discipline", "pacing", 0.4, 5.0,
            f"habitual positive splits (ratio {pac.get('mean_ratio')}) — fast start, fade",
            "Practice even / slightly-negative splits; start 'embarrassingly controlled', especially on runs."))

    # Rank by severity × time-impact; recovery (if present) always leads.
    cands.sort(key=lambda c: c.severity * c.time_impact, reverse=True)
    recovery = [c for c in cands if c.area == "recovery"]
    rest = [c for c in cands if c.area != "recovery"]
    ranked = (recovery + rest)[:3]

    this_week = [{"area": c.area, "action": c.recommendation} for c in ranked]
    headline = (ranked[0].name + " — " + ranked[0].evidence) if ranked else \
        "No clear limiter — keep building consistently."

    return {
        "limiters": [asdict(c) for c in ranked],
        "headline": headline,
        "this_week": this_week,
        "data_gaps": strength.get("data_gaps") or [],
        # The compact contract the LLM coach reads (no raw time-series).
        "coach_input": {
            "goal": goal,
            "readiness": {
                "score": rd.get("score"), "band": rd.get("band"),
                "overtraining": ot_level, "garmin_status": _g(load, "garmin_native", "training_status"),
            },
            "ranked_limiters": [
                {"name": c.name, "area": c.area, "evidence": c.evidence,
                 "time_impact": c.time_impact} for c in ranked
            ],
            "key_metrics": {
                "decoupling_pct": dec.get("average_pct"),
                "compromised_fade_pct": fade,
                "critical_speed_pace": _g(running, "critical_speed", "cs_pace_sec_per_km"),
                "vo2max": profile_vo2max,
                "ef_trend_per_week": vo2_trend,
                "intensity_low_pct": idist.get("low_pct"),
                "tsb": _g(load, "ctl_atl_tsb", "tsb"),
                "ctl": _g(load, "ctl_atl_tsb", "ctl"),
                "hrv_status": _g(load, "hrv", "status"),
                "weakest_stations": (sp.get("weakest") or sp.get("weakest_3") or []),
                "hybrid_balance": {"run": hb.get("run_index"), "strength": hb.get("strength_index")},
            },
            "data_gaps": strength.get("data_gaps") or [],
        },
    }
