"""File-based state — ``data/*.json`` is the database (single user, git-tracked).

No DB, no ORM. Each domain object is a Pydantic model serialized to JSON. Git is
the history and backup. Override the location with ``PACEFORGE_DATA_DIR``.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

from paceforge.models.plan import TrainingPlan
from paceforge.models.profile import RecentActivity, UserFitnessProfile

DATA_DIR = Path(os.getenv("PACEFORGE_DATA_DIR", "data"))

_DETAILS_CACHE: dict[int, dict] | None = None
_DETAILS_CACHE_TIME = 0.0
_DETAILS_CACHE_TTL = 300  # 5 minutes

# Global serialization boundary for every data/ write.  This is process-wide and
# is acquired in the runner's direct endpoints plus action/scheduler paths so
# that concurrent mutations cannot interleave on the same file.
_WRITE_LOCK_PATH = DATA_DIR / ".write.lock"
_WRITE_LOCK = threading.RLock()


def _path(name: str) -> Path:
    return DATA_DIR / name


def _raw_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: write a sibling temp file, then rename — a crash mid-write must
    # never leave a truncated JSON file behind.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload)
    os.replace(tmp, path)


def _write(path: Path, payload: str) -> None:
    """Serialized wrapper around the atomic writer.

    Acquires ``store._WRITE_LOCK`` so that concurrent writes across endpoints,
    jobs, or CLI entrypoints cannot interleave on the same file and produce torn
    JSON. Group writes that must be atomic as one block (serialize then call
    ``store._write`` once per file).
    """
    with _WRITE_LOCK:
        _raw_write(path, payload)



def load_profile() -> UserFitnessProfile | None:
    p = _path("profile.json")
    return UserFitnessProfile.model_validate_json(p.read_text()) if p.exists() else None


_EMPTY = (None, [], {}, "")


def save_profile(profile: UserFitnessProfile) -> None:
    """Persist the profile, preserving prior non-empty fields the fresh fetch dropped.

    Garmin's wellness endpoints intermittently return null for VO2max/HRV/readiness
    for a given day. Without this merge a sync would overwrite good values with null,
    so we only let a new value replace an existing one when the new value is non-empty.
    """
    existing = load_profile()
    if existing is not None:
        merged = profile.model_dump()
        old = existing.model_dump()
        for field, value in merged.items():
            if value in _EMPTY and old.get(field) not in _EMPTY:
                merged[field] = old[field]
        profile = UserFitnessProfile.model_validate(merged)
    _write(_path("profile.json"), profile.model_dump_json(indent=2))


# Slim daily-wellness fields persisted to history.jsonl for trend metrics
# (CTL/ATL/TSB, HRV baseline, sleep debt) — profile.json only ever holds "today".
_HISTORY_FIELDS = (
    "vo2_max", "resting_hr", "max_hr", "hrv_status", "hrv_last_night",
    "training_readiness", "training_status", "training_load_7day", "load_focus",
    "body_battery_current", "body_battery_high", "body_battery_low",
    "sleep_score", "sleep_duration_seconds", "sleep_deep_seconds",
    "sleep_rem_seconds", "sleep_light_seconds", "stress_avg", "stress_high",
    "weekly_mileage_km", "hill_score", "respiration_avg_sleep", "spo2_avg",
    "running_tolerance",
)

# max_hr and weekly_mileage_km derive from the activity list, so they survive a
# failed wellness fetch — a row carrying only those two is still a failed sync.
_WELLNESS_FIELDS = tuple(f for f in _HISTORY_FIELDS if f not in ("max_hr", "weekly_mileage_km"))


def append_daily_history(profile: UserFitnessProfile) -> dict:
    """Upsert one slim wellness snapshot for the profile's date into history.jsonl.

    Trend metrics need this daily series — every day not stored is permanently
    lost. Garmin endpoints fail intermittently, so a fetch can hand us a profile
    full of nulls; unlike profile.json (see save_profile) history rows are
    permanent, so an all-null snapshot is skipped outright and a partial one is
    merged field-by-field with any existing row for the same date.
    """
    p = profile.model_dump()
    date = p.get("profile_date")
    if not date:
        return {"written": False, "reason": "no_profile_date"}
    date = str(date)
    row = {"date": date, **{f: p.get(f) for f in _HISTORY_FIELDS}}
    if all(row[f] in _EMPTY for f in _WELLNESS_FIELDS):
        return {"written": False, "reason": "skipped_all_null"}
    rows = load_history()
    for old in rows:
        if old.get("date") == date:
            for f in _HISTORY_FIELDS:
                if row[f] in _EMPTY and old.get(f) not in _EMPTY:
                    row[f] = old[f]
            break
    rows = [r for r in rows if r.get("date") != date]
    rows.append(row)
    rows.sort(key=lambda r: r.get("date") or "")
    _write(_path("history.jsonl"),
           "\n".join(json.dumps(r, default=str) for r in rows) + "\n")
    return {"written": True, "reason": None}


def repair_history() -> dict:
    """One-shot cleanup of history.jsonl: drop all-null rows, merge duplicate dates.

    Rows written before append_daily_history learned to skip failed syncs can be
    entirely null (every wellness field empty) — they poison the trend series.
    """
    rows = load_history()
    merged: dict[str, dict] = {}
    dropped = 0
    for row in rows:
        date = str(row.get("date") or "")
        if not date or all(row.get(f) in _EMPTY for f in _WELLNESS_FIELDS):
            dropped += 1
            continue
        if date in merged:
            for f in _HISTORY_FIELDS:
                if row.get(f) not in _EMPTY:
                    merged[date][f] = row[f]
        else:
            merged[date] = {"date": date, **{f: row.get(f) for f in _HISTORY_FIELDS}}
    out = sorted(merged.values(), key=lambda r: r["date"])
    _write(_path("history.jsonl"),
           "\n".join(json.dumps(r, default=str) for r in out) + "\n")
    return {"kept": len(out), "dropped": dropped}


def load_rpe() -> dict:
    """Athlete-entered session RPE (data/rpe.json): {"entries": [...]}; empty if absent.

    Entries carry activity_id (Garmin-recorded sessions) or just a date (unrecorded
    ones). sRPE load for HR-less strength/HYROX work depends on these.
    """
    p = _path("rpe.json")
    if not p.exists():
        return {"entries": []}
    try:
        d = json.loads(p.read_text()) or {}
        return {"entries": d.get("entries") or []}
    except (json.JSONDecodeError, OSError):
        return {"entries": []}


def upsert_rpe(entry: dict) -> dict:
    """Insert or replace one RPE entry (keyed by activity_id, else by date)."""
    entries = load_rpe()["entries"]
    aid = entry.get("activity_id")
    if aid is not None:
        entries = [e for e in entries if e.get("activity_id") != aid]
    else:
        entries = [e for e in entries
                   if e.get("activity_id") is not None or e.get("date") != entry.get("date")]
    entries.append(entry)
    entries.sort(key=lambda e: str(e.get("date") or ""))
    data = {"entries": entries}
    _write(_path("rpe.json"), json.dumps(data, indent=2))
    return data


def rpe_by_activity() -> dict[int, dict]:
    """RPE entries keyed by activity_id (date-only entries excluded)."""
    return {e["activity_id"]: e for e in load_rpe()["entries"]
            if e.get("activity_id") is not None}


def load_token_meta() -> dict | None:
    """Garmin token provenance (data/token-meta.json) — written by ``login()``."""
    p = _path("token-meta.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()) or None
    except (json.JSONDecodeError, OSError):
        return None


def save_token_meta(meta: dict) -> None:
    _write(_path("token-meta.json"), json.dumps(meta, indent=2, default=str))


def load_sync_status() -> dict | None:
    """The last sync attempt's outcome (data/sync-status.json); None if never synced."""
    p = _path("sync-status.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()) or None
    except (json.JSONDecodeError, OSError):
        return None


def save_sync_status(status: dict) -> None:
    _write(_path("sync-status.json"), json.dumps(status, indent=2, default=str))


def load_all_details() -> dict[int, dict]:
    """Every stored per-activity detail, keyed by activity_id (for the fitness engines).

    Cached with 5-minute TTL to avoid repeated full-directory scans on the Fitness tab.
    """
    global _DETAILS_CACHE, _DETAILS_CACHE_TIME
    now = time.time()
    if _DETAILS_CACHE is not None and (now - _DETAILS_CACHE_TIME) < _DETAILS_CACHE_TTL:
        return _DETAILS_CACHE

    out: dict[int, dict] = {}
    ddir = _path("details")
    if not ddir.exists():
        _DETAILS_CACHE = out
        _DETAILS_CACHE_TIME = now
        return out
    for f in ddir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if d.get("activity_id") is not None:
                out[int(d["activity_id"])] = d
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    _DETAILS_CACHE = out
    _DETAILS_CACHE_TIME = now
    return out


def load_hyrox_results() -> list[dict]:
    """The HYROX race results list (data/hyrox.json -> 'results'); [] if absent."""
    p = _path("hyrox.json")
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get("results", []) or []
    except (json.JSONDecodeError, OSError, AttributeError):
        return []


def load_hyrox_analysis() -> dict | None:
    """The built HYROX analysis (data/hyrox_analysis.json, from build_site_data)."""
    p = _path("hyrox_analysis.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()) or None
    except (json.JSONDecodeError, OSError):
        return None


def load_benchmarks() -> dict | None:
    """User-entered strength/HYROX benchmarks (data/benchmarks.json); None if unset."""
    p = _path("benchmarks.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()) or None
    except (json.JSONDecodeError, OSError):
        return None


def save_benchmarks(benchmarks: dict) -> None:
    _write(_path("benchmarks.json"), json.dumps(benchmarks, indent=2))


def save_hyrox_results(cached: dict) -> None:
    """Persist scraped HYROX races (the HyroxCachedData shape) to data/hyrox.json."""
    _write(_path("hyrox.json"), json.dumps(cached, indent=2, default=str))


def save_hyrox_preview(preview: dict) -> None:
    """Persist a transient race-search preview (for the web pick-list) to disk."""
    _write(_path("hyrox_preview.json"), json.dumps(preview, indent=2, default=str))


def load_events() -> list[dict]:
    """Upcoming races/runs the athlete entered (data/events.json); [] if absent."""
    p = _path("events.json")
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()) or []
    except (json.JSONDecodeError, OSError):
        return []


def save_events(events: list[dict]) -> None:
    _write(_path("events.json"), json.dumps(events, indent=2, default=str))


def load_history() -> list[dict]:
    """All stored daily wellness snapshots, oldest first."""
    p = _path("history.jsonl")
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            out.append(json.loads(line))
    return out


def load_plan() -> TrainingPlan | None:
    p = _path("plan.json")
    return TrainingPlan.model_validate_json(p.read_text()) if p.exists() else None


def save_plan(plan: TrainingPlan) -> None:
    _write(_path("plan.json"), plan.model_dump_json(indent=2))


def load_activities() -> list[RecentActivity]:
    p = _path("activities.json")
    if not p.exists():
        return []
    return [RecentActivity.model_validate(a) for a in json.loads(p.read_text())]


def load_bike_rides() -> list[dict]:
    """App-recorded indoor rides (never on Garmin) — feed these into the load maths."""
    p = _path("bike") / "rides.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("rides", [])


def save_activities(activities: list[RecentActivity]) -> None:
    """Merge a fresh activity window into the stored history (union by activity_id).

    A sync only sees a recent lookback window; replacing the file would cap history
    at that window. We union with what's already stored, letting the fresh copy win
    for any overlapping id, and keep the newest first.
    """
    by_id = {a.activity_id: a for a in load_activities()}
    for a in activities:
        by_id[a.activity_id] = a
    merged = sorted(by_id.values(), key=lambda a: str(a.start_time or ""), reverse=True)
    payload = json.dumps([a.model_dump(mode="json") for a in merged], indent=2)
    _write(_path("activities.json"), payload)


# ── Per-activity detail (splits/HR/weather for the web charts) ────────


def _detail_path(activity_id: int | str) -> Path:
    return _path("details") / f"{activity_id}.json"


def has_detail(activity_id: int | str) -> bool:
    return _detail_path(activity_id).exists()


def load_detail(activity_id: int | str) -> dict | None:
    p = _detail_path(activity_id)
    return json.loads(p.read_text()) if p.exists() else None


def save_detail(activity_id: int | str, detail: dict) -> None:
    _write(_detail_path(activity_id), json.dumps(detail, indent=2, default=str))
    invalidate_details_cache()


def invalidate_details_cache() -> None:
    """Clear the load_all_details() cache after writes."""
    global _DETAILS_CACHE, _DETAILS_CACHE_TIME
    _DETAILS_CACHE = None
    _DETAILS_CACHE_TIME = 0.0
