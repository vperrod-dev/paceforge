"""First-class calendar items — the athlete's whole training week, not just runs.

2026-08-10 decoupling: scheduling a class/ride/swim no longer requires (or
touches) a running plan. ``data/calendar.json`` holds these; the running plan
contributes its workouts to the same calendar VIEW but owns none of this.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class ScheduledItem(BaseModel):
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    date: date
    sport: str = "Cardio"                  # free-text label: Cardio/HYROX/Swim/Bike/...
    title: str = ""
    duration_min: int = 45
    distance_km: float | None = None
    notes: str = ""
    source: str = "manual"                 # "manual" | "race"
    garmin_workout_id: int | None = None   # set when pushed to the Garmin calendar
    matched_activity_ids: list[str] = Field(default_factory=list)
    completed: bool = False
