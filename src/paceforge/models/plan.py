"""Training plan and workout models."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class WorkoutStepType(StrEnum):
    WARMUP = "warmup"
    COOLDOWN = "cooldown"
    INTERVAL = "interval"
    RECOVERY = "recovery"
    ACTIVE = "active"  # steady-state (easy, tempo, marathon pace)
    REST = "rest"


class IntensityTarget(StrEnum):
    """How the target is expressed."""

    PACE = "pace"
    HEART_RATE = "heart_rate"
    OPEN = "open"  # no specific target (by feel)


class WorkoutStep(BaseModel):
    step_type: WorkoutStepType
    description: str = ""
    duration_seconds: float | None = None
    distance_meters: float | None = None
    target_type: IntensityTarget = IntensityTarget.OPEN
    target_low: float | None = Field(None, description="Low end — pace (sec/km) or HR (bpm)")
    target_high: float | None = Field(None, description="High end — pace (sec/km) or HR (bpm)")
    repeat_count: int | None = Field(None, description="For repeat groups only")
    steps: list[WorkoutStep] | None = Field(None, description="Sub-steps for repeat groups")


class WorkoutType(StrEnum):
    EASY_RUN = "easy_run"
    LONG_RUN = "long_run"
    TEMPO = "tempo"
    INTERVALS = "intervals"
    RECOVERY = "recovery_run"
    THRESHOLD = "threshold"
    RACE_PACE = "race_pace"
    FARTLEK = "fartlek"
    HYROX_MIXED = "hyrox_mixed"
    CROSS_TRAINING = "cross_training"
    REST = "rest"
    PROGRESSIVE = "progressive"
    HILLS = "hills"
    STRIDES = "strides"
    SPEED = "speed"
    VO2MAX = "vo2max"
    EASY_WITH_STRIDES = "easy_with_strides"
    LONG_RUN_PROGRESSIVE = "long_run_progressive"
    LONG_RUN_WITH_RACE_PACE = "long_run_with_race_pace"


class TrainingPurpose(StrEnum):
    AEROBIC_BASE = "aerobic_base"
    VO2MAX = "vo2max"
    LACTATE_THRESHOLD = "lactate_threshold"
    RUNNING_ECONOMY = "running_economy"
    SPEED_NEUROMUSCULAR = "speed_neuromuscular"
    RACE_SPECIFICITY = "race_specificity"
    ENDURANCE = "endurance"
    RECOVERY = "recovery"
    MENTAL_TOUGHNESS = "mental_toughness"


class Workout(BaseModel):
    workout_type: WorkoutType
    name: str
    description: str = ""
    scheduled_date: date | None = None
    estimated_duration_seconds: float | None = None
    estimated_distance_meters: float | None = None
    steps: list[WorkoutStep] = Field(default_factory=list)
    notes: str = ""
    purpose: TrainingPurpose | None = None
    cadence_target: int | None = None
    # Completion tracking
    completed: bool = False
    matched_activity_ids: list[int] = Field(default_factory=list, description="Garmin activity IDs matched to this workout")
    completion_analysis: str | None = Field(None, description="AI analysis of how the workout went")
    completion_metrics: dict | None = Field(None, description="Actual vs planned metrics from matched activity")
    garmin_workout_id: int | None = Field(None, description="Garmin workout id from the last push (delete-by-id on re-push)")

    @model_validator(mode="before")
    @classmethod
    def _migrate_matched_activity_id(cls, data: dict) -> dict:
        """Migrate legacy matched_activity_id (int) → matched_activity_ids (list)."""
        if isinstance(data, dict):
            old_id = data.pop("matched_activity_id", None)
            if old_id is not None and not data.get("matched_activity_ids"):
                data["matched_activity_ids"] = [old_id]
        return data

    @property
    def matched_activity_id(self) -> int | None:
        """Primary matched activity ID (backward compat)."""
        return self.matched_activity_ids[0] if self.matched_activity_ids else None

    @matched_activity_id.setter
    def matched_activity_id(self, value: int | None) -> None:
        if value is None:
            self.matched_activity_ids = []
        elif value not in self.matched_activity_ids:
            self.matched_activity_ids = [value]
    # User feedback
    user_rpe: int | None = Field(None, description="Rate of Perceived Exertion (1-10)")
    user_notes: str | None = Field(None, description="User notes about how the workout felt")


class TrainingWeek(BaseModel):
    week_number: int
    phase: str = Field(default="", description="e.g. 'Base', 'Build', 'Peak', 'Taper'")
    total_distance_km: float | None = None
    workouts: list[Workout] = Field(default_factory=list)
    focus: str = Field(default="", description="Week's training focus summary")


class TrainingPlan(BaseModel):
    plan_id: str = ""
    name: str
    goal_type: str
    target_date: date
    target_time_seconds: float | None = None
    total_weeks: int
    weeks: list[TrainingWeek] = Field(default_factory=list)
    created_at: date = Field(default_factory=date.today)

    # Paces derived from VDOT (sec/km)
    easy_pace: float | None = None
    marathon_pace: float | None = None
    threshold_pace: float | None = None
    interval_pace: float | None = None
    repetition_pace: float | None = None
    vdot: float | None = Field(default=None, description="Derived VDOT value used for pace calculation")
    pace_source: str = Field(default="", description="How training paces were derived (e.g. 'Lactate threshold speed', 'VO2 Max')")

    # AI-generated plan context
    rationale: str = Field(default="", description="AI explanation of why this plan was designed this way")
    tips: list[str] = Field(default_factory=list, description="Personalised training tips from the AI coach")
    athlete_summary: str = Field(default="", description="Summary of athlete profile data used to generate the plan")

    # Plan acceptance state
    accepted: bool = False

    # AI adaptation tracking
    last_ai_review: str | None = Field(None, description="ISO timestamp of last AI plan review")
    adaptation_notes: str | None = Field(None, description="AI explanation of last plan adaptation")
