"""Auto-segment a recorded HYROX sim/race into run / station / roxzone.

Garmin's typed-splits endpoint tags each split by run/walk/stand (or interval
active/rest) detection. That typing lets us slice a recorded session into its
run, station-work, and roxzone-transition portions with zero manual tagging —
feeding the load model and closing the plan -> race -> analysis loop.
"""

from __future__ import annotations

from typing import Any

# Garmin typed-split type -> HYROX segment. RUN = the 1 km runs, STAND / ACTIVE =
# working a station, WALK / REST / recovery = the roxzone transitions between them.
_SEGMENT_OF: dict[str, str] = {
    "RWD_RUN": "run",
    "RWD_WALK": "roxzone",
    "RWD_STAND": "station",
    "INTERVAL_ACTIVE": "station",
    "INTERVAL_REST": "roxzone",
    "INTERVAL_RECOVERY": "roxzone",
    "INTERVAL_WARMUP": "roxzone",
    "INTERVAL_COOLDOWN": "roxzone",
}

_SEGMENTS = ("run", "station", "roxzone")


def classify_split(split_type: str | None) -> str | None:
    """Map a Garmin typed-split ``type`` to run / station / roxzone (None if unknown)."""
    return _SEGMENT_OF.get((split_type or "").upper())


def _empty() -> dict[str, Any]:
    return {"count": 0, "duration_s": 0.0, "distance_m": 0.0}


def segment_activity(detail: dict | None) -> dict[str, Any] | None:
    """Aggregate one stored detail's typed splits into run/station/roxzone totals.

    Returns None when the activity carries no classifiable typed splits (i.e. it
    is not a segmentable HYROX-style recording), so callers can simply skip it.
    """
    typed = (detail or {}).get("typed_splits")
    if not typed:
        return None
    buckets = {seg: _empty() for seg in _SEGMENTS}
    classified = 0
    for ts in typed:
        if not isinstance(ts, dict):
            continue
        seg = classify_split(ts.get("type"))
        if seg is None:
            continue
        bucket = buckets[seg]
        bucket["count"] += 1
        bucket["duration_s"] += ts.get("duration_s") or 0
        bucket["distance_m"] += ts.get("distance_m") or 0
        classified += 1
    if not classified:
        return None
    total = sum(b["duration_s"] for b in buckets.values())
    for bucket in buckets.values():
        bucket["duration_s"] = round(bucket["duration_s"], 1)
        bucket["distance_m"] = round(bucket["distance_m"], 1)
        bucket["share_pct"] = round(100 * bucket["duration_s"] / total, 1) if total else 0.0
    return {"segments": buckets, "total_duration_s": round(total, 1)}


def segment_hyrox_activities(activities: list, details: dict | None) -> list[dict[str, Any]]:
    """Per-activity run/station/roxzone breakdown for every recording with typed splits.

    Iterates the activity list (newest first) so the load model and the UI read
    a dated, named segmentation instead of a manual RPE tag.
    """
    details = details or {}
    out: list[dict[str, Any]] = []
    for act in activities or []:
        aid = getattr(act, "activity_id", None)
        seg = segment_activity(details.get(aid))
        if seg is None:
            continue
        start = getattr(act, "start_time", None)
        out.append({
            "activity_id": aid,
            "name": getattr(act, "name", None),
            "date": start.date().isoformat() if start else None,
            **seg,
        })
    return out
