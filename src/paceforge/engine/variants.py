"""Session-variant library — ordered progressions per quality-slot type.

Each variant is ``(factory_method, kwargs, min_weekly_km)``. Lists are ORDERED
by Canova's levers — more reps → longer reps → shorter recovery, at fixed
pace — so walking a list forward is always a visible step up on last week.
``min_weekly_km`` volume-gates a variant: a session must fit the week that
hosts it (Daniels' per-zone caps at low mileage).
"""

from __future__ import annotations

Variant = tuple[str, dict, float]

VARIANTS: dict[str, list[Variant]] = {
    "vo2max": [
        ("vo2max_intervals", {"reps": 4, "rep_min": 3.0}, 22),
        ("vo2max_intervals", {"reps": 5, "rep_min": 3.0}, 25),
        ("vo2max_intervals", {"reps": 5, "rep_min": 3.5}, 27),
        ("vo2max_intervals", {"reps": 6, "rep_min": 3.5}, 30),
        ("ladder", {"rungs_min": [5, 4, 3, 4, 5], "pace_key": "interval"}, 32),
    ],
    "speed_400s": [
        ("speed_reps", {"reps": 8, "rep_m": 400}, 22),
        ("speed_reps", {"reps": 10, "rep_m": 400}, 25),
        ("speed_reps", {"reps": 6, "rep_m": 600, "rest_sec": 120}, 28),
        ("speed_reps", {"reps": 12, "rep_m": 400}, 30),
    ],
    "speed_200s": [
        ("speed_reps", {"reps": 10, "rep_m": 200, "rest_sec": 60}, 16),
        ("speed_reps", {"reps": 12, "rep_m": 200, "rest_sec": 60}, 20),
        ("speed_reps", {"reps": 8, "rep_m": 300, "rest_sec": 90}, 24),
    ],
    "hills": [
        ("hills", {"reps": 6}, 18),
        ("hills", {"reps": 8}, 22),
        ("hills", {"reps": 10}, 26),
        ("hills", {"reps": 12}, 30),
    ],
    "fartlek": [
        ("fartlek", {"total_min": 30}, 18),
        ("fartlek", {"total_min": 40}, 24),
        ("fartlek", {"total_min": 45}, 30),
    ],
    "tempo": [
        ("tempo", {"tempo_km": 4}, 20),
        ("tempo", {"tempo_km": 5}, 23),
        ("tempo", {"tempo_km": 6}, 26),
        ("progressive_tempo", {"blocks": 3, "block_min": 8}, 28),
        ("tempo", {"tempo_km": 8}, 32),
    ],
    "threshold_cruise": [
        ("threshold_cruise_intervals", {"reps": 3, "rep_min": 6}, 22),
        ("threshold_cruise_intervals", {"reps": 4, "rep_min": 6}, 25),
        ("threshold_cruise_intervals", {"reps": 3, "rep_km": 2.0}, 28),
        ("threshold_cruise_intervals", {"reps": 5, "rep_min": 6, "rest_sec": 45}, 30),
        ("threshold_cruise_intervals", {"reps": 4, "rep_km": 2.0, "rest_sec": 45}, 34),
    ],
    "alternations": [
        ("alternations", {"reps": 3}, 24),
        ("alternations", {"reps": 4}, 27),
        ("alternations", {"reps": 5}, 31),
    ],
    "steady_m": [
        ("steady_m_pace", {"km": 5}, 20),
        ("steady_m_pace", {"km": 7}, 25),
        ("steady_m_pace", {"km": 9}, 30),
    ],
    "race_pace": [
        ("race_pace_intervals", {"reps": 3, "rep_km": 1.0, "pace_key": "race"}, 22),
        ("race_pace_intervals", {"reps": 4, "rep_km": 1.0, "pace_key": "race"}, 25),
        ("race_pace_intervals", {"reps": 5, "rep_km": 1.0, "pace_key": "race"}, 28),
        ("race_pace_intervals", {"reps": 4, "rep_km": 1.5, "pace_key": "race"}, 31),
    ],
    # HYROX run-under-fatigue: 1km threshold repeats growing toward the race's 8x1km.
    "compromised_km": [
        ("race_pace_intervals", {"reps": 4, "rep_km": 1.0, "pace_key": "threshold"}, 20),
        ("race_pace_intervals", {"reps": 5, "rep_km": 1.0, "pace_key": "threshold"}, 23),
        ("race_pace_intervals", {"reps": 6, "rep_km": 1.0, "pace_key": "threshold"}, 26),
        ("race_pace_intervals", {"reps": 8, "rep_km": 1.0, "pace_key": "threshold"}, 30),
    ],
}


def pick_variant(
    slot_type: str, week_in_phase: int, deload: bool, week_km: float
) -> Variant:
    """Select the variant for a slot: walk the ordered table by position in the
    phase, step BACK one on a deload week, and only consider variants whose
    ``min_weekly_km`` the week can host."""
    table = VARIANTS[slot_type]
    eligible = [v for v in table if v[2] <= week_km] or table[:1]
    idx = min(week_in_phase, len(eligible) - 1)
    if deload:
        idx = max(idx - 1, 0)
    return eligible[idx]
