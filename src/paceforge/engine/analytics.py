"""Performance analytics engine — computes derived insights from athlete data.

All functions are pure: they take a UserFitnessProfile and return a dataclass.
No API calls, no side effects — just math and domain knowledge.

LEGACY: this one-shot, snapshot-based generation is superseded by Fitness 2.0
(durability.py / load.py / strength.py / limiters.py, driven off time-series).
It still powers `paceforge analyze` / analytics.json for the Overview page; new
metrics belong in the Fitness 2.0 modules, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from paceforge.engine.vdot import (
    RACE_DISTANCES,
    normalize_lt_speed,
    paces_from_vdot,
    vdot_from_race,
)
from paceforge.models.profile import UserFitnessProfile

# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class AthleteSnapshot:
    fitness_level: str  # Beginner / Intermediate / Advanced / Elite
    vdot: float | None
    training_status: str
    strengths: list[str]
    weaknesses: list[str]
    training_age_estimate: str  # e.g. "1-2 years", "5+ years"


@dataclass
class AerobicAnalysis:
    vo2max_category: str  # e.g. "Superior", "Excellent", "Good", "Fair", "Poor"
    vo2max_interpretation: str
    aerobic_ratio: float  # 0-1, fraction of training that is aerobic
    anaerobic_ratio: float
    threshold_quality: str  # e.g. "Strong", "Moderate", "Weak"
    threshold_pct_of_vo2max: float | None  # LT pace as % of VO2max-equivalent pace
    cardiac_efficiency: str  # "High" / "Moderate" / "Low"
    cardiac_drift_indicator: float | None  # HR/pace slope across runs
    aerobic_decoupling_pct: float | None  # % drift in long runs


@dataclass
class RunningEconomy:
    cadence_avg: float | None
    cadence_grade: str  # "Optimal" / "Slightly Low" / "Low" / "High"
    stride_length_avg: float | None
    stride_grade: str
    gct_avg: float | None  # ground contact time ms
    gct_grade: str  # "Excellent" / "Good" / "Needs Work"
    vert_osc_avg: float | None  # cm
    vert_osc_grade: str
    vert_ratio_avg: float | None
    overall_grade: str  # A / B / C / D
    inefficiencies: list[str]


@dataclass
class LoadRecovery:
    load_status: str  # "Overreaching" / "Optimal" / "Undertraining"
    training_load_7day: float | None
    load_focus: str | None
    hrv_assessment: str  # "Stable" / "Improving" / "Declining" / "Unknown"
    sleep_quality: str  # "Excellent" / "Good" / "Fair" / "Poor" / "Unknown"
    sleep_score: int | None
    body_battery: int | None
    stress_level: str  # "Low" / "Moderate" / "High" / "Unknown"
    fatigue_risk: str  # "Low" / "Moderate" / "High"
    recovery_tips: list[str]


@dataclass
class RacePrediction:
    distance: str
    distance_meters: float
    predicted_seconds: float
    pace_sec_per_km: float
    confidence: str  # "High" / "Moderate" / "Low"


@dataclass
class RacePredictions:
    vdot: float | None
    predictions: list[RacePrediction]
    fatigue_resistance: float  # ratio: marathon pace / 5k pace (higher = more durable)
    distance_bias: str  # "Speed-biased" / "Balanced" / "Endurance-biased"
    optimal_distance: str  # e.g. "10K", "Half Marathon"
    consistency_notes: list[str]  # gaps between predicted vs actual
    equivalent_performances: list[dict]  # cross-distance mapping


@dataclass
class HyroxPredictions:
    sustainable_1km_pace: float | None  # sec/km under fatigue
    race_1km_splits: list[float]  # 8 predicted split times (seconds)
    total_running_time: float | None  # sum of 8 splits
    predicted_event_range: tuple[float, float] | None  # (low, high) total event time seconds
    compromised_running_class: str  # "Strong" / "Moderate" / "Severe Fade"
    pace_fade_pct: float  # degradation from run 1 to run 8
    energy_system_pct: dict[str, float]  # aerobic / threshold / anaerobic / muscular_endurance
    transition_cost_seconds: float  # estimated extra time per transition
    top_limiters: list[str]
    fade_pattern: str  # "Stable" / "Positive Split" / "Blow-up Risk"


@dataclass
class KeySession:
    name: str
    description: str
    pace_target: str  # e.g. "4:30-4:45/km"
    hr_target: str  # e.g. "155-165 bpm"


@dataclass
class Benchmark:
    metric: str
    current: str
    target_4wk: str
    target_8wk: str
    target_12wk: str


@dataclass
class TrainingRecommendations:
    split_pct: dict[str, float]  # aerobic / threshold / high_intensity / strength_hyrox
    key_sessions: list[KeySession]
    hyrox_progression: list[str]
    recovery_optimization: list[str]
    benchmarks: list[Benchmark]


# ── Helper utilities ─────────────────────────────────────────────────

def _fmt_pace(sec_per_km: float) -> str:
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}"


# Back-compat alias — canonical implementation lives in engine.vdot.
_normalize_lt_speed = normalize_lt_speed


def _estimate_vdot(profile: UserFitnessProfile) -> float | None:
    """Best VDOT estimate from available data.

    Priority: VO2max (most reliable from Garmin) > Garmin race predictions
    > Personal records > LT speed (often unreliable units).
    """
    # VO2max direct — Garmin's own calculation, most reliable
    if profile.vo2_max and profile.vo2_max > 10:
        return profile.vo2_max
    # Garmin race predictions
    for rp in profile.race_predictions:
        dist = RACE_DISTANCES.get(rp.distance)
        if dist and rp.predicted_seconds > 0:
            return vdot_from_race(dist, rp.predicted_seconds)
    # Personal records
    for pr in profile.personal_records:
        dist = RACE_DISTANCES.get(pr.distance)
        if dist and pr.time_seconds > 0:
            return vdot_from_race(dist, pr.time_seconds)
    # LT speed (only if we can validate the unit)
    lt_speed = _normalize_lt_speed(profile.lactate_threshold_speed)
    if lt_speed:
        lt_dist = lt_speed * 3600
        v = vdot_from_race(lt_dist, 3600)
        if v and 20 < v < 85:  # sanity check
            return v
    # Fastest recent run as last resort
    running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km and a.distance_meters > 2000]
    if running:
        fastest = min(running, key=lambda a: a.avg_pace_sec_per_km or 999)
        if fastest.avg_pace_sec_per_km:
            v = vdot_from_race(fastest.distance_meters, fastest.duration_seconds)
            if v and v > 10:
                return v
    return None


def _predict_race_time(vdot: float, distance_meters: float) -> float:
    """Predict race time in seconds for a given VDOT and distance.

    Uses the inverse Daniels formula: find time t such that
    vdot_from_race(distance, t) == vdot. Solved via binary search.
    """
    # Reasonable bounds: 2 min for 1km to 6 hours for marathon
    lo, hi = 120, 6 * 3600
    if distance_meters <= 1500:
        lo, hi = 60, 600
    elif distance_meters <= 5500:
        lo, hi = 600, 3600
    elif distance_meters <= 11000:
        lo, hi = 1200, 5400
    elif distance_meters <= 22000:
        lo, hi = 2400, 10800

    for _ in range(60):
        mid = (lo + hi) / 2
        est_vdot = vdot_from_race(distance_meters, mid)
        if est_vdot > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ── Compute functions ────────────────────────────────────────────────


def compute_athlete_snapshot(profile: UserFitnessProfile) -> AthleteSnapshot:
    vdot = _estimate_vdot(profile)
    km = profile.weekly_mileage_km or 0

    # Fitness level classification
    if vdot and vdot >= 60 and km >= 70:
        level = "Elite"
    elif vdot and vdot >= 50 and km >= 40:
        level = "Advanced"
    elif vdot and vdot >= 40 and km >= 20:
        level = "Intermediate"
    elif vdot and vdot >= 30:
        level = "Beginner"
    else:
        # Fall back to mileage only
        if km >= 60:
            level = "Advanced"
        elif km >= 25:
            level = "Intermediate"
        else:
            level = "Beginner"

    # Training age: use actual data if available, not guesses
    if profile.fitness_age:
        age_est = f"Fitness age: {profile.fitness_age}"
    elif level == "Elite":
        age_est = "5+ years (est.)"
    elif level == "Advanced":
        age_est = "3-5 years (est.)"
    elif level == "Intermediate":
        age_est = "1-3 years (est.)"
    else:
        age_est = "< 1 year (est.)"

    # Strengths & weaknesses
    strengths: list[str] = []
    weaknesses: list[str] = []

    if vdot and vdot >= 50:
        strengths.append("Strong aerobic engine")
    elif vdot and vdot < 40:
        weaknesses.append("Aerobic capacity needs development")

    if profile.lactate_threshold_speed and profile.lactate_threshold_speed > 0:
        lt_pace = 1000 / profile.lactate_threshold_speed
        if lt_pace < 300:
            strengths.append("Excellent lactate threshold")
        elif lt_pace > 360:
            weaknesses.append("Lactate threshold could improve")

    if km >= 50:
        strengths.append("High training volume")
    elif km < 20:
        weaknesses.append("Low weekly mileage — volume-limited")

    running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km]
    if running:
        cadences = [a.avg_running_cadence for a in running if a.avg_running_cadence]
        if cadences:
            avg_cad = sum(cadences) / len(cadences)
            if 170 <= avg_cad <= 185:
                strengths.append("Good running cadence")
            elif avg_cad < 165:
                weaknesses.append("Low cadence — may indicate overstriding")

        gcts = [a.avg_ground_contact_time for a in running if a.avg_ground_contact_time]
        if gcts:
            avg_gct = sum(gcts) / len(gcts)
            if avg_gct < 230:
                strengths.append("Efficient ground contact time")
            elif avg_gct > 270:
                weaknesses.append("High ground contact time — running form inefficiency")

    if profile.hrv_status and profile.hrv_status.upper() in ("BALANCED",):
        strengths.append("Balanced HRV — good recovery capacity")
    elif profile.hrv_status and profile.hrv_status.upper() in ("LOW", "BELOW_BASELINE", "UNBALANCED"):
        weaknesses.append("Low HRV — possible accumulated fatigue")

    if profile.training_status and profile.training_status.lower() in ("productive", "peaking"):
        strengths.append(f"Training status: {profile.training_status}")
    elif profile.training_status and profile.training_status.lower() in ("overreaching", "detraining", "unproductive", "maintaining"):
        weaknesses.append(f"Training status: {profile.training_status}")

    # Ensure at least something
    if not strengths:
        strengths.append("Consistent training habit")
    if not weaknesses:
        weaknesses.append("No critical weaknesses identified")

    return AthleteSnapshot(
        fitness_level=level,
        vdot=round(vdot, 1) if vdot else None,
        training_status=profile.training_status or "Unknown",
        strengths=strengths[:5],
        weaknesses=weaknesses[:5],
        training_age_estimate=age_est,
    )


def compute_aerobic_analysis(profile: UserFitnessProfile) -> AerobicAnalysis:
    vdot = _estimate_vdot(profile)
    vo2 = profile.vo2_max

    # VO2max category
    if vo2 and vo2 >= 60:
        cat = "Superior"
    elif vo2 and vo2 >= 52:
        cat = "Excellent"
    elif vo2 and vo2 >= 45:
        cat = "Good"
    elif vo2 and vo2 >= 38:
        cat = "Fair"
    elif vo2:
        cat = "Below Average"
    else:
        cat = "Unknown"

    interpretation = f"VO2 Max {vo2:.1f} — {cat} aerobic capacity" if vo2 else "VO2 Max data not available"

    # Aerobic vs anaerobic balance from training effects
    running = [a for a in profile.recent_activities if a.training_effect_aerobic is not None]
    aer_sum = sum(a.training_effect_aerobic or 0 for a in running)
    ana_sum = sum(a.training_effect_anaerobic or 0 for a in running)
    total = aer_sum + ana_sum
    aer_ratio = aer_sum / total if total > 0 else 0.8
    ana_ratio = ana_sum / total if total > 0 else 0.2

    # Threshold quality
    thr_pct = None
    lt_speed = _normalize_lt_speed(profile.lactate_threshold_speed)
    if lt_speed and vdot:
        paces = paces_from_vdot(vdot)
        lt_pace = 1000 / lt_speed
        thr_pct = round((paces.threshold / lt_pace) * 100, 1) if lt_pace > 0 else None

    if thr_pct and thr_pct >= 95:
        thr_quality = "Strong — threshold close to VDOT-predicted"
    elif thr_pct and thr_pct >= 85:
        thr_quality = "Moderate — room to close threshold gap"
    elif thr_pct:
        thr_quality = "Needs work — threshold underperforming"
    else:
        thr_quality = "Insufficient data"

    # Cardiac efficiency: average HR / pace ratio across easy runs
    easy_runs = [a for a in profile.recent_activities
                 if a.avg_pace_sec_per_km and a.avg_hr and a.avg_pace_sec_per_km > 300]
    if easy_runs:
        hr_per_pace = [a.avg_hr / a.avg_pace_sec_per_km for a in easy_runs]
        avg_ratio = sum(hr_per_pace) / len(hr_per_pace)
        if avg_ratio < 0.4:
            card_eff = "High — low HR relative to pace"
        elif avg_ratio < 0.5:
            card_eff = "Moderate"
        else:
            card_eff = "Low — HR elevated relative to pace"
    else:
        card_eff = "Insufficient data"
        avg_ratio = None

    # Aerobic decoupling: compare first-half vs second-half HR/pace in long runs
    long_runs = [a for a in profile.recent_activities
                 if a.distance_meters and a.distance_meters > 12000 and a.avg_hr]
    decoupling = None
    if len(long_runs) >= 2:
        # Rough proxy: compare HR differences across long runs at similar paces
        sorted_lr = sorted(long_runs, key=lambda a: a.start_time)
        recent = sorted_lr[-1]
        older = sorted_lr[0]
        if older.avg_pace_sec_per_km and recent.avg_pace_sec_per_km and older.avg_hr and recent.avg_hr:
            pace_diff_pct = abs(recent.avg_pace_sec_per_km - older.avg_pace_sec_per_km) / older.avg_pace_sec_per_km
            if pace_diff_pct < 0.05:  # similar pace
                hr_drift = ((recent.avg_hr - older.avg_hr) / older.avg_hr) * 100
                decoupling = round(hr_drift, 1)

    return AerobicAnalysis(
        vo2max_category=cat,
        vo2max_interpretation=interpretation,
        aerobic_ratio=round(aer_ratio, 2),
        anaerobic_ratio=round(ana_ratio, 2),
        threshold_quality=thr_quality,
        threshold_pct_of_vo2max=thr_pct,
        cardiac_efficiency=card_eff,
        cardiac_drift_indicator=round(avg_ratio, 3) if avg_ratio else None,
        aerobic_decoupling_pct=decoupling,
    )


def compute_running_economy(profile: UserFitnessProfile) -> RunningEconomy:
    running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km]
    inefficiencies: list[str] = []

    # Cadence
    cadences = [a.avg_running_cadence for a in running if a.avg_running_cadence]
    avg_cad = sum(cadences) / len(cadences) if cadences else None
    if avg_cad:
        if 175 <= avg_cad <= 185:
            cad_grade = "Optimal"
        elif 170 <= avg_cad < 175:
            cad_grade = "Good"
        elif 165 <= avg_cad < 170:
            cad_grade = "Slightly Low"
            inefficiencies.append(f"Cadence averaging {avg_cad:.0f} spm — target 170-180 for better economy")
        elif avg_cad < 165:
            cad_grade = "Low"
            inefficiencies.append(f"Low cadence ({avg_cad:.0f} spm) suggests overstriding — shorten stride, increase turnover")
        else:
            cad_grade = "High"
    else:
        cad_grade = "No data"

    # Stride length
    strides = [a.avg_stride_length for a in running if a.avg_stride_length]
    avg_stride = sum(strides) / len(strides) if strides else None
    if avg_stride:
        if 1.0 <= avg_stride <= 1.4:
            stride_grade = "Normal"
        elif avg_stride < 1.0:
            stride_grade = "Short"
            inefficiencies.append("Short stride length — may limit speed potential")
        else:
            stride_grade = "Long"
            inefficiencies.append("Long stride — check for overstriding and braking forces")
    else:
        stride_grade = "No data"

    # Ground contact time
    gcts = [a.avg_ground_contact_time for a in running if a.avg_ground_contact_time]
    avg_gct = sum(gcts) / len(gcts) if gcts else None
    if avg_gct:
        if avg_gct < 220:
            gct_grade = "Excellent"
        elif avg_gct < 245:
            gct_grade = "Good"
        elif avg_gct < 270:
            gct_grade = "Average"
            inefficiencies.append(f"GCT {avg_gct:.0f}ms — work on foot strike and hip extension")
        else:
            gct_grade = "Needs Work"
            inefficiencies.append(f"High GCT ({avg_gct:.0f}ms) — focus on plyometrics, hip strength, and calf stiffness")
    else:
        gct_grade = "No data"

    # Vertical oscillation
    vos = [a.avg_vertical_oscillation for a in running if a.avg_vertical_oscillation]
    avg_vo = sum(vos) / len(vos) if vos else None
    if avg_vo:
        if avg_vo < 7:
            vo_grade = "Excellent"
        elif avg_vo < 9:
            vo_grade = "Good"
        elif avg_vo < 11:
            vo_grade = "Average"
            inefficiencies.append(f"Vertical oscillation {avg_vo:.1f}cm — wasted vertical energy")
        else:
            vo_grade = "Excessive"
            inefficiencies.append(f"High vertical oscillation ({avg_vo:.1f}cm) — focus on forward lean and hip drive")
    else:
        vo_grade = "No data"

    # Vertical ratio
    vrs = [a.avg_vertical_ratio for a in running if a.avg_vertical_ratio]
    avg_vr = sum(vrs) / len(vrs) if vrs else None

    # Overall grade
    grades = {"Excellent": 4, "Good": 3, "Optimal": 4, "Normal": 3, "Average": 2,
              "Slightly Low": 2, "Short": 2, "Long": 2, "Low": 1, "High": 1,
              "Needs Work": 1, "Excessive": 1, "No data": 0}
    scored = [grades.get(g, 0) for g in [cad_grade, gct_grade, vo_grade] if g != "No data"]
    if scored:
        avg_score = sum(scored) / len(scored)
        if avg_score >= 3.5:
            overall = "A"
        elif avg_score >= 2.5:
            overall = "B"
        elif avg_score >= 1.5:
            overall = "C"
        else:
            overall = "D"
    else:
        overall = "—"

    return RunningEconomy(
        cadence_avg=round(avg_cad, 1) if avg_cad else None,
        cadence_grade=cad_grade,
        stride_length_avg=round(avg_stride, 2) if avg_stride else None,
        stride_grade=stride_grade,
        gct_avg=round(avg_gct, 0) if avg_gct else None,
        gct_grade=gct_grade,
        vert_osc_avg=round(avg_vo, 1) if avg_vo else None,
        vert_osc_grade=vo_grade,
        vert_ratio_avg=round(avg_vr, 1) if avg_vr else None,
        overall_grade=overall,
        inefficiencies=inefficiencies,
    )


def compute_load_recovery(profile: UserFitnessProfile) -> LoadRecovery:
    # Training load status
    ts = (profile.training_status or "").lower()
    if ts in ("overreaching",):
        load_status = "Overreaching"
    elif ts in ("productive", "peaking", "maintaining"):
        load_status = "Optimal"
    elif ts in ("detraining", "unproductive"):
        load_status = "Undertraining"
    elif ts in ("recovery",):
        load_status = "Recovery"
    else:
        load_status = "Unknown"

    # HRV assessment
    hrv = (profile.hrv_status or "").upper()
    if hrv in ("BALANCED",):
        hrv_assess = "Stable"
    elif hrv in ("HIGH", "ABOVE_BASELINE"):
        hrv_assess = "Improving"
    elif hrv in ("LOW", "BELOW_BASELINE", "UNBALANCED"):
        hrv_assess = "Declining"
    else:
        hrv_assess = "Unknown"

    # Sleep quality
    ss = profile.sleep_score
    if ss and ss >= 80:
        sleep_q = "Excellent"
    elif ss and ss >= 60:
        sleep_q = "Good"
    elif ss and ss >= 40:
        sleep_q = "Fair"
    elif ss:
        sleep_q = "Poor"
    else:
        sleep_q = "Unknown"

    # Stress level
    sa = profile.stress_avg
    if sa and sa <= 25:
        stress_lvl = "Low"
    elif sa and sa <= 50:
        stress_lvl = "Moderate"
    elif sa:
        stress_lvl = "High"
    else:
        stress_lvl = "Unknown"

    # Fatigue risk composite
    risk_score = 0
    if ts in ("overreaching",):
        risk_score += 3
    if hrv in ("LOW", "BELOW_BASELINE", "UNBALANCED"):
        risk_score += 2
    if ss and ss < 50:
        risk_score += 2
    if sa and sa > 50:
        risk_score += 1
    bb = profile.body_battery_current
    if bb and bb < 30:
        risk_score += 2
    elif bb and bb < 50:
        risk_score += 1

    if risk_score >= 5:
        fatigue = "High"
    elif risk_score >= 3:
        fatigue = "Moderate"
    else:
        fatigue = "Low"

    # Recovery tips
    tips: list[str] = []
    if fatigue == "High":
        tips.append("Consider a deload week — reduce training volume by 30-40%")
    if hrv in ("LOW", "BELOW_BASELINE", "UNBALANCED"):
        tips.append("Prioritize sleep and reduce high-intensity sessions until HRV stabilizes")
    if ss and ss < 60:
        tips.append(f"Sleep score {ss} — aim for 7-9 hours of quality sleep, consistent bed/wake times")
    if sa and sa > 40:
        tips.append("Elevated stress detected — incorporate recovery walks, breathing exercises, or yoga")
    if bb and bb < 40:
        tips.append(f"Body battery at {bb}% — schedule rest day or easy recovery only")
    if not tips:
        tips.append("Recovery indicators look good — maintain current training rhythm")

    return LoadRecovery(
        load_status=load_status,
        training_load_7day=profile.training_load_7day,
        load_focus=profile.load_focus,
        hrv_assessment=hrv_assess,
        sleep_quality=sleep_q,
        sleep_score=ss,
        body_battery=bb,
        stress_level=stress_lvl,
        fatigue_risk=fatigue,
        recovery_tips=tips,
    )


def compute_race_predictions(profile: UserFitnessProfile) -> RacePredictions:
    vdot = _estimate_vdot(profile)

    distances = [
        ("1km", 1000),
        ("5K", 5000),
        ("10K", 10000),
        ("Half Marathon", 21097.5),
        ("Marathon", 42195),
    ]

    # Build lookup of Garmin's own predictions (most reliable)
    _key_map = {"5K": "5K", "10K": "10K", "HALF_MARATHON": "Half Marathon", "MARATHON": "Marathon"}
    garmin_pred_map: dict[str, float] = {}
    for rp in profile.race_predictions:
        mapped = _key_map.get(rp.distance)
        if mapped and rp.predicted_seconds > 0:
            garmin_pred_map[mapped] = rp.predicted_seconds

    predictions: list[RacePrediction] = []
    for name, dist_m in distances:
        # Prefer Garmin's own prediction for that distance
        garmin_sec = garmin_pred_map.get(name)
        if garmin_sec:
            pred_sec = garmin_sec
            conf = "High"
        elif vdot:
            pred_sec = _predict_race_time(vdot, dist_m)
            conf = "Moderate" if profile.vo2_max else "Low"
        else:
            continue

        pace = pred_sec / (dist_m / 1000)
        predictions.append(RacePrediction(
            distance=name,
            distance_meters=dist_m,
            predicted_seconds=round(pred_sec, 1),
            pace_sec_per_km=round(pace, 1),
            confidence=conf,
        ))

    # Fatigue resistance: ratio of marathon pace to 5k pace (higher = more durable)
    fr = 0.0
    if len(predictions) >= 5:
        five_k_pace = predictions[1].pace_sec_per_km
        marathon_pace = predictions[4].pace_sec_per_km
        if five_k_pace > 0:
            fr = round(marathon_pace / five_k_pace, 3)

    # Distance bias
    if fr > 1.18:
        bias = "Speed-biased (stronger at short distances)"
    elif fr < 1.12:
        bias = "Endurance-biased (stronger at longer distances)"
    else:
        bias = "Balanced across distances"

    # Optimal distance
    if fr < 1.10:
        opt_dist = "Marathon"
    elif fr < 1.14:
        opt_dist = "Half Marathon"
    elif fr < 1.18:
        opt_dist = "10K"
    else:
        opt_dist = "5K"

    # Consistency check: compare VDOT predictions vs Garmin predictions vs PBs
    notes: list[str] = []
    garmin_preds = {rp.distance: rp.predicted_seconds for rp in profile.race_predictions}
    pbs = {pr.distance: pr.time_seconds for pr in profile.personal_records}

    for pred in predictions:
        dist_key = pred.distance
        # Normalize keys for comparison
        key_map = {"Half Marathon": "HALF_MARATHON", "Marathon": "MARATHON", "5K": "5K", "10K": "10K"}
        norm_key = key_map.get(dist_key, dist_key)

        if norm_key in garmin_preds:
            garmin_sec = garmin_preds[norm_key]
            diff_pct = ((pred.predicted_seconds - garmin_sec) / garmin_sec) * 100
            if abs(diff_pct) > 5:
                direction = "slower" if diff_pct > 0 else "faster"
                notes.append(f"{dist_key}: VDOT predicts {abs(diff_pct):.0f}% {direction} than Garmin estimate")

        if norm_key in pbs:
            pb_sec = pbs[norm_key]
            diff_pct = ((pred.predicted_seconds - pb_sec) / pb_sec) * 100
            if diff_pct < -5:
                notes.append(f"{dist_key}: Actual PB is slower than predicted — hidden potential or outdated PB")
            elif diff_pct > 5:
                notes.append(f"{dist_key}: Actual PB better than predicted — PB may reflect peak form")

    # Equivalent performances
    equivs: list[dict] = []
    if vdot:
        for name, dist_m in distances:
            pred_sec = _predict_race_time(vdot, dist_m)
            m, s = divmod(int(pred_sec), 60)
            h, m = divmod(m, 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            equivs.append({"distance": name, "time": time_str, "pace": _fmt_pace(pred_sec / (dist_m / 1000))})

    return RacePredictions(
        vdot=round(vdot, 1) if vdot else None,
        predictions=predictions,
        fatigue_resistance=fr,
        distance_bias=bias,
        optimal_distance=opt_dist,
        consistency_notes=notes,
        equivalent_performances=equivs,
    )


def compute_hyrox_predictions(profile: UserFitnessProfile) -> HyroxPredictions:
    """Model HYROX running performance from running fitness data.

    HYROX format: 8 x 1km running legs separated by functional stations.
    Key factors: lactate threshold, fatigue resistance, HR recovery capacity.
    """
    vdot = _estimate_vdot(profile)
    paces = paces_from_vdot(vdot) if vdot else None

    # Base 1km pace: between threshold and interval pace
    if paces:
        # HYROX race pace is slightly slower than threshold (fatigue-adjusted)
        base_pace = paces.threshold + 15  # ~15 sec slower than threshold per km
    else:
        lt_speed = _normalize_lt_speed(profile.lactate_threshold_speed)
        if lt_speed:
            base_pace = (1000 / lt_speed) + 15
        else:
            # Rough estimate from recent runs
            running = [a for a in profile.recent_activities if a.avg_pace_sec_per_km]
            if running:
                avg_pace = sum(a.avg_pace_sec_per_km for a in running if a.avg_pace_sec_per_km) / len(running)
                base_pace = avg_pace - 20  # assume they can race ~20s/km faster than training average
            else:
                base_pace = None

    if base_pace is None:
        return HyroxPredictions(
            sustainable_1km_pace=None,
            race_1km_splits=[],
            total_running_time=None,
            predicted_event_range=None,
            compromised_running_class="Insufficient Data",
            pace_fade_pct=0,
            energy_system_pct={"aerobic": 50, "threshold": 25, "anaerobic": 15, "muscular_endurance": 10},
            transition_cost_seconds=0,
            top_limiters=["Insufficient data to assess"],
            fade_pattern="Unknown",
        )

    # Pace degradation model across 8 runs
    # Factors: aerobic fitness (VO2max), fatigue resistance, training volume
    base_fade_per_run = 3.0  # seconds per km per run segment (default)

    # Adjust fade based on fitness
    if vdot and vdot >= 55:
        base_fade_per_run = 1.5
    elif vdot and vdot >= 48:
        base_fade_per_run = 2.5
    elif vdot and vdot >= 42:
        base_fade_per_run = 3.5
    else:
        base_fade_per_run = 5.0

    # Volume adjustment: higher mileage = better fatigue resistance
    km = profile.weekly_mileage_km or 0
    if km >= 50:
        base_fade_per_run *= 0.8
    elif km < 20:
        base_fade_per_run *= 1.3

    # Generate 8 splits with progressive degradation
    splits: list[float] = []
    for i in range(8):
        # Exponential fade: more in later runs
        fade = base_fade_per_run * (1 + i * 0.15)
        split_pace = base_pace + fade * i
        split_time = split_pace  # 1km = pace in sec
        splits.append(round(split_time, 1))

    total_running = round(sum(splits), 1)
    pace_fade_pct = round(((splits[-1] - splits[0]) / splits[0]) * 100, 1) if splits[0] > 0 else 0

    # Compromised running classification
    if pace_fade_pct < 8:
        comp_class = "Strong Compromised Runner"
    elif pace_fade_pct < 15:
        comp_class = "Moderate Drop-off"
    else:
        comp_class = "Severe Fade"

    # Energy system contribution
    energy = {
        "aerobic": 45.0,
        "threshold": 30.0,
        "anaerobic": 15.0,
        "muscular_endurance": 10.0,
    }
    # Adjust based on pace profile
    if paces and base_pace < paces.threshold:
        # Racing above threshold — more anaerobic
        energy["threshold"] = 35.0
        energy["anaerobic"] = 18.0
        energy["aerobic"] = 37.0

    # Transition cost (station → run)
    # Better aerobic fitness = faster recovery
    if vdot and vdot >= 55:
        transition_cost = 8.0
    elif vdot and vdot >= 48:
        transition_cost = 12.0
    elif vdot and vdot >= 42:
        transition_cost = 18.0
    else:
        transition_cost = 25.0

    # Total event estimate: running + 8 transitions + station time (estimated)
    # Average station time for intermediate: ~2:00-2:30 per station
    station_est = 8 * 135  # 8 stations × ~2:15 each
    total_event_low = total_running + 8 * transition_cost + station_est * 0.85
    total_event_high = total_running + 8 * transition_cost + station_est * 1.15

    # Fade pattern
    if pace_fade_pct < 5:
        fade_pattern = "Stable"
    elif pace_fade_pct < 12:
        fade_pattern = "Positive Split"
    else:
        fade_pattern = "Blow-up Risk"

    # Top limiters
    limiters: list[str] = []
    if vdot and vdot < 45:
        limiters.append("Aerobic capacity — VO2max limits sustained pace")
    if pace_fade_pct > 12:
        limiters.append("Fatigue resistance — pace drops significantly across runs")
    lt_speed_norm = _normalize_lt_speed(profile.lactate_threshold_speed)
    if lt_speed_norm and paces and (1000 / lt_speed_norm) > paces.threshold + 10:
        limiters.append("Lactate tolerance — threshold underperforming vs fitness")
    if km < 30:
        limiters.append("Training volume — insufficient mileage for race demands")
    if not profile.training_status or profile.training_status.lower() not in ("productive", "peaking"):
        limiters.append("Training consistency — not in productive training cycle")

    running = [a for a in profile.recent_activities if a.avg_running_cadence]
    if running:
        avg_cad = sum(a.avg_running_cadence for a in running if a.avg_running_cadence) / len(running)
        if avg_cad < 170:
            limiters.append("Running economy — low cadence adds energy cost per km")

    if not limiters:
        limiters.append("Well-rounded profile — focus on race-specific preparation")

    return HyroxPredictions(
        sustainable_1km_pace=round(base_pace, 1),
        race_1km_splits=splits,
        total_running_time=total_running,
        predicted_event_range=(round(total_event_low), round(total_event_high)),
        compromised_running_class=comp_class,
        pace_fade_pct=pace_fade_pct,
        energy_system_pct=energy,
        transition_cost_seconds=transition_cost,
        top_limiters=limiters[:5],
        fade_pattern=fade_pattern,
    )


def compute_training_recommendations(
    profile: UserFitnessProfile,
    snapshot: AthleteSnapshot,
) -> TrainingRecommendations:
    """Generate training recommendations based on athlete profile and snapshot."""
    vdot = _estimate_vdot(profile)
    paces = paces_from_vdot(vdot) if vdot else None
    level = snapshot.fitness_level

    # Training split
    if level == "Beginner":
        split = {"aerobic": 70, "threshold": 12, "high_intensity": 8, "strength_hyrox": 10}
    elif level == "Intermediate":
        split = {"aerobic": 60, "threshold": 18, "high_intensity": 10, "strength_hyrox": 12}
    elif level == "Advanced":
        split = {"aerobic": 55, "threshold": 20, "high_intensity": 12, "strength_hyrox": 13}
    else:  # Elite
        split = {"aerobic": 50, "threshold": 22, "high_intensity": 14, "strength_hyrox": 14}

    # Key sessions
    sessions: list[KeySession] = []

    if paces:
        sessions.append(KeySession(
            name="Threshold Intervals",
            description="4-5 × 6 min at threshold pace with 90s recovery",
            pace_target=f"{_fmt_pace(paces.threshold)}/km",
            hr_target=f"{int(profile.lactate_threshold_hr or 0)} bpm" if profile.lactate_threshold_hr else "85-90% max HR",
        ))
        sessions.append(KeySession(
            name="VO2max Intervals",
            description="5 × 3 min at interval pace with equal recovery",
            pace_target=f"{_fmt_pace(paces.interval)}/km",
            hr_target="90-95% max HR",
        ))
        sessions.append(KeySession(
            name="Long Aerobic Run",
            description=f"90-120 min at easy pace — build to {int((profile.weekly_mileage_km or 30) * 0.35)}km",
            pace_target=f"{_fmt_pace(paces.easy_low)}-{_fmt_pace(paces.easy_high)}/km",
            hr_target="65-75% max HR",
        ))
        sessions.append(KeySession(
            name="Compromised Run",
            description="4 × (functional station + 1km at race pace) — simulate HYROX fatigue",
            pace_target=f"{_fmt_pace(paces.threshold + 15)}/km",
            hr_target="80-90% max HR",
        ))
        sessions.append(KeySession(
            name="Tempo Run",
            description="20-30 min sustained effort at marathon pace",
            pace_target=f"{_fmt_pace(paces.marathon)}/km",
            hr_target="75-85% max HR",
        ))
    else:
        sessions.append(KeySession(
            name="Easy Aerobic Run",
            description="45-60 min at conversational pace",
            pace_target="Conversational effort",
            hr_target="Zone 2 (65-75% max HR)",
        ))

    # HYROX progression
    hyrox_prog = [
        "Improve 1km repeatability: 8 × 1km at race pace with 2-min rest, targeting < 5% pace fade",
        "Reduce station-to-run transition time: practice sled push → immediate 400m run at goal pace",
        "Build compromised running endurance: weekly session of mixed functional + running under fatigue",
    ]

    # Recovery optimization
    recovery = []
    if profile.hrv_status and profile.hrv_status.lower() == "low":
        recovery.append("Prioritize 8+ hours of sleep to restore HRV baseline")
    if profile.sleep_score and profile.sleep_score < 70:
        recovery.append("Improve sleep hygiene: consistent schedule, cool room, no screens 1hr before bed")
    if profile.stress_avg and profile.stress_avg > 40:
        recovery.append("Incorporate daily 10-min breathwork or meditation to manage stress load")
    recovery.append("Schedule deload week every 3-4 weeks: 60% volume, maintain intensity")
    if profile.body_battery_current and profile.body_battery_current < 50:
        recovery.append("Body battery low — focus on recovery nutrition (protein + carbs within 30min of training)")

    # Benchmarks
    benchmarks: list[Benchmark] = []
    if vdot:
        current_vdot = round(vdot, 1)
        benchmarks.append(Benchmark(
            metric="VDOT",
            current=str(current_vdot),
            target_4wk=str(round(current_vdot + 1, 1)),
            target_8wk=str(round(current_vdot + 2, 1)),
            target_12wk=str(round(current_vdot + 3, 1)),
        ))
    if paces:
        benchmarks.append(Benchmark(
            metric="Threshold Pace",
            current=f"{_fmt_pace(paces.threshold)}/km",
            target_4wk=f"{_fmt_pace(paces.threshold - 3)}/km",
            target_8wk=f"{_fmt_pace(paces.threshold - 6)}/km",
            target_12wk=f"{_fmt_pace(paces.threshold - 10)}/km",
        ))
    km = profile.weekly_mileage_km or 0
    benchmarks.append(Benchmark(
        metric="Weekly Mileage",
        current=f"{km:.0f} km",
        target_4wk=f"{km * 1.1:.0f} km",
        target_8wk=f"{km * 1.2:.0f} km",
        target_12wk=f"{km * 1.3:.0f} km",
    ))
    if profile.resting_hr:
        benchmarks.append(Benchmark(
            metric="Resting HR",
            current=f"{profile.resting_hr} bpm",
            target_4wk=f"{max(profile.resting_hr - 1, 35)} bpm",
            target_8wk=f"{max(profile.resting_hr - 2, 35)} bpm",
            target_12wk=f"{max(profile.resting_hr - 3, 35)} bpm",
        ))

    return TrainingRecommendations(
        split_pct=split,
        key_sessions=sessions,
        hyrox_progression=hyrox_prog,
        recovery_optimization=recovery,
        benchmarks=benchmarks,
    )


def compute_all(profile: UserFitnessProfile) -> dict:
    """Run all analytics and return a JSON-serializable dict."""
    snapshot = compute_athlete_snapshot(profile)
    aerobic = compute_aerobic_analysis(profile)
    economy = compute_running_economy(profile)
    load_rec = compute_load_recovery(profile)
    race_preds = compute_race_predictions(profile)
    hyrox = compute_hyrox_predictions(profile)
    recommendations = compute_training_recommendations(profile, snapshot)

    def _dc_to_dict(obj):
        """Convert dataclass to dict, handling nested dataclasses and lists."""
        from dataclasses import asdict
        return asdict(obj)

    return {
        "snapshot": _dc_to_dict(snapshot),
        "aerobic": _dc_to_dict(aerobic),
        "economy": _dc_to_dict(economy),
        "load_recovery": _dc_to_dict(load_rec),
        "race_predictions": _dc_to_dict(race_preds),
        "hyrox": _dc_to_dict(hyrox),
        "recommendations": _dc_to_dict(recommendations),
    }
