"""User fitness profile and Garmin-sourced metrics."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ── Health data models (Apple Health / Google Health Connect) ─────────


class HealthDataPoint(BaseModel):
    """Single health measurement."""
    date: str  # ISO date string YYYY-MM-DD
    value: float
    source: str = "unknown"  # "apple_health", "google_health_connect", "garmin"


class BodyComposition(BaseModel):
    """Body composition time-series data."""
    height_cm: float | None = None
    weight_kg: list[HealthDataPoint] = Field(default_factory=list)
    bmi: list[HealthDataPoint] = Field(default_factory=list)
    body_fat_pct: list[HealthDataPoint] = Field(default_factory=list)
    lean_body_mass_kg: list[HealthDataPoint] = Field(default_factory=list)


class HealthData(BaseModel):
    """Top-level health data wrapper for a user."""
    sources: list[str] = Field(default_factory=list)  # e.g. ["apple_health"]
    last_sync: str | None = None  # ISO datetime
    body_composition: BodyComposition = Field(default_factory=BodyComposition)


class HRZone(BaseModel):
    zone: int
    low_bpm: int
    high_bpm: int


class RacePrediction(BaseModel):
    distance: str  # "5K", "10K", "HALF_MARATHON", "MARATHON"
    predicted_seconds: float


class PersonalRecord(BaseModel):
    distance: str  # e.g. "5K", "10K", "HALF_MARATHON", "MARATHON"
    time_seconds: float
    record_date: str | None = None


class RecentActivity(BaseModel):
    activity_id: int
    name: str
    activity_type: str
    start_time: datetime
    distance_meters: float
    duration_seconds: float
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_sec_per_km: float | None = None
    calories: int | None = None
    training_effect_aerobic: float | None = None
    training_effect_anaerobic: float | None = None
    vo2_max_value: float | None = None
    avg_running_cadence: float | None = None
    # Running dynamics
    avg_stride_length: float | None = Field(None, description="Average stride length in meters")
    avg_ground_contact_time: float | None = Field(None, description="Average ground contact time in ms")
    avg_vertical_oscillation: float | None = Field(None, description="Average vertical oscillation in cm")
    avg_vertical_ratio: float | None = Field(None, description="Average vertical ratio in %")
    avg_power: float | None = Field(None, description="Average running power in watts")
    elevation_gain: float | None = Field(None, description="Total elevation gain in meters")
    avg_respiration_rate: float | None = Field(None, description="Average respiration rate in breaths/min")


class UserFitnessProfile(BaseModel):
    """Aggregated fitness snapshot pulled from Garmin Connect."""

    garmin_display_name: str | None = None
    vo2_max: float | None = Field(None, description="Current VO2 max estimate")
    resting_hr: int | None = None
    max_hr: int | None = None
    hr_zones: list[HRZone] = Field(default_factory=list)
    training_readiness: float | None = Field(None, description="Garmin Training Readiness score")
    training_status: str | None = Field(None, description="e.g. 'Productive', 'Detraining', 'Peaking'")
    hrv_status: str | None = Field(None, description="e.g. 'Balanced', 'Low', 'High'")
    hrv_last_night: float | None = None
    weekly_mileage_km: float | None = Field(None, description="Average weekly running distance (km)")
    lactate_threshold_hr: float | None = Field(None, description="Heart rate at lactate threshold (bpm)")
    lactate_threshold_speed: float | None = Field(None, description="Speed at lactate threshold (m/s)")
    endurance_score: float | None = Field(None, description="Garmin endurance score")
    weight_kg: float | None = Field(None, description="Body weight in kg")
    race_predictions: list[RacePrediction] = Field(default_factory=list)
    personal_records: list[PersonalRecord] = Field(default_factory=list)
    recent_activities: list[RecentActivity] = Field(default_factory=list)
    profile_date: date = Field(default_factory=date.today)

    # Body Battery
    body_battery_current: int | None = Field(None, description="Current body battery level (0-100)")
    body_battery_high: int | None = None
    body_battery_low: int | None = None

    # Sleep
    sleep_score: int | None = Field(None, description="Last night sleep quality score")
    sleep_duration_seconds: float | None = None
    sleep_deep_seconds: float | None = None
    sleep_light_seconds: float | None = None
    sleep_rem_seconds: float | None = None
    sleep_awake_seconds: float | None = None

    # Stress
    stress_avg: int | None = Field(None, description="Daily average stress level")
    stress_high: int | None = None
    stress_low: int | None = None

    # Training Load
    training_load_7day: float | None = Field(None, description="7-day cumulative training load")
    load_focus: str | None = Field(None, description="Load focus: Low Aerobic / High Aerobic / Anaerobic")

    # Fitness Age
    fitness_age: int | None = Field(None, description="Garmin estimated fitness age")

    # Hill Score — uphill-running strength/endurance composite, independent of
    # the flat-ground endurance score above.
    hill_score: float | None = Field(None, description="Garmin Hill Score (uphill-running composite)")

    # Overnight respiration & pulse ox — illness early-warning signals.
    respiration_avg_sleep: float | None = Field(
        None, description="Average overnight respiration rate (breaths/min)"
    )
    spo2_avg: float | None = Field(None, description="Average overnight SpO2 (%)")
    spo2_lowest: float | None = Field(None, description="Lowest overnight SpO2 (%)")

    # Extra sleep-derived signals (same get_sleep_data call, kept since 2026-08-10).
    skin_temp_deviation_c: float | None = Field(
        None, description="Overnight skin-temperature deviation from baseline (°C)"
    )
    sleep_restless_moments: int | None = Field(
        None, description="Count of restless moments during last night's sleep"
    )
    body_battery_overnight_change: int | None = Field(
        None, description="Body Battery change over last night's sleep (recharge)"
    )
    sleep_avg_stress: float | None = Field(
        None, description="Average stress level during sleep"
    )

    # Running tolerance — Garmin's impact-load capacity estimate.
    running_tolerance: float | None = Field(
        None, description="Garmin running tolerance (impact-load capacity)"
    )


class GoalType(StrEnum):
    FIVE_K = "5K"
    TEN_K = "10K"
    HALF_MARATHON = "HALF_MARATHON"
    MARATHON = "MARATHON"
    HYROX = "HYROX"
    CUSTOM = "CUSTOM"


class ExperienceLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


_ALL_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_DEFAULT_DAYS: dict[int, list[str]] = {
    3: ["tuesday", "thursday", "sunday"],
    4: ["tuesday", "thursday", "saturday", "sunday"],
    5: ["tuesday", "wednesday", "thursday", "saturday", "sunday"],
    6: ["monday", "tuesday", "wednesday", "thursday", "saturday", "sunday"],
    7: _ALL_DAYS,
}


def default_training_days(n: int = 5) -> list[str]:
    """Return a sensible default set of training days for *n* days/week."""
    return list(_DEFAULT_DAYS.get(n, _DEFAULT_DAYS[5]))


class TrainingGoal(BaseModel):
    goal_type: GoalType
    target_date: date
    target_time_seconds: float | None = Field(
        None, description="Target finish time in seconds (optional)"
    )
    experience_level: ExperienceLevel | None = None
    training_days: list[str] = Field(
        default_factory=lambda: default_training_days(5),
        description="Which days of the week to train (e.g. ['monday','wednesday','friday','saturday','sunday'])",
    )
    long_run_day: str = Field(default="sunday", description="Preferred long run day")
    start_date: date | None = Field(None, description="Optional plan start date")
    custom_easy_pace: float | None = Field(None, description="User-provided easy pace in sec/km")
    custom_marathon_pace: float | None = Field(None, description="User-provided marathon pace in sec/km")
    custom_threshold_pace: float | None = Field(None, description="User-provided threshold pace in sec/km")
    # Intake truth (2026-08-10): the athlete's stated fitness governs the plan;
    # Garmin history only prefills/suggests. recent_race_* derives VDOT ahead of
    # any device metric; current_weekly_km anchors the volume ramp.
    recent_race_distance: str | None = Field(None, description="Stated recent race/TT distance key (5K/10K/HALF_MARATHON/MARATHON)")
    recent_race_seconds: float | None = Field(None, description="Stated recent race/TT finish time in seconds")
    current_weekly_km: float | None = Field(None, description="Self-declared current comfortable weekly volume (km)")

    @property
    def max_days_per_week(self) -> int:
        return len(self.training_days)
