"""Core actions shared by the CLI and the MCP server.

One module, two entrypoints — ``cli.py`` and ``mcp_server.py`` are thin wrappers
over these functions. All state lives in ``data/*.json`` via :mod:`paceforge.store`.

Garmin auth: a one-time login (interactive ``login()``, or the portal's Connect
Garmin) dumps a ~1-year token to ``PACEFORGE_GARMIN_TOKEN_DIR``; every sync
re-dumps the refreshed one. ``export_token()`` packs that dir into a base64 blob
and ``GARMIN_TOKEN`` unpacks it again — the backup/restore path for moving an
athlete's session to another machine without a new password + MFA round.
"""

from __future__ import annotations

import base64
import getpass
import io
import json
import logging
import os
import sys
import tarfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from paceforge import store
from paceforge.engine.analytics import compute_all
from paceforge.engine.validate import validate_plan
from paceforge.garmin.client import GarminClient
from paceforge.models.plan import (
    IntensityTarget,
    TrainingPlan,
    TrainingWeek,
    Workout,
    WorkoutStepType,
    WorkoutType,
)
from paceforge.models.profile import HealthDataPoint

logger = logging.getLogger(__name__)

# ── Garmin auth ──────────────────────────────────────────────────────


def _token_dir() -> Path:
    return Path(os.getenv("PACEFORGE_GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()


def _has_token(token_dir: Path) -> bool:
    return token_dir.exists() and any(token_dir.iterdir())


def _materialize_token(token_dir: Path) -> None:
    """Unpack a GARMIN_TOKEN blob into an empty token dir (see module docstring)."""
    blob = os.getenv("GARMIN_TOKEN")
    if not blob or _has_token(token_dir):
        return
    token_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(blob)), mode="r:gz") as tar:
        tar.extractall(token_dir, filter="data")  # refuse path traversal / device members


def _export_token(token_dir: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in sorted(token_dir.iterdir()):
            if f.is_file():
                tar.add(f, arcname=f.name)
    return base64.b64encode(buf.getvalue()).decode()


def _purge_token(token_dir: Path) -> None:
    """Remove any persisted Garmin token files so the next login is real."""
    if not token_dir.exists():
        return
    for f in list(token_dir.glob("*")):
        if f.is_file():
            f.unlink(missing_ok=True)


def _auto_login() -> None:
    """Refresh a missing/expired Garmin token using PACEFORGE_GARMIN_PASSWORD.

    This is the migration-period recovery path that removes the dependency on
    manual portal logins or external secrets. If the credentials require MFA,
    the function raises with a clear human instruction so the job can alert
    the runner instead of failing silently for reasons no one understands.
    """
    token_dir = _token_dir()
    _purge_token(token_dir)
    email = _garmin_email()
    password = os.environ.get("PACEFORGE_GARMIN_PASSWORD")
    if not password:
        raise RuntimeError(
            "GARMIN_TOKEN is not valid and PACEFORGE_GARMIN_PASSWORD is not set. "
            "Set PACEFORGE_GARMIN_EMAIL/PASSWORD in the runner env to enable "
            "autonomous token refresh, or run `paceforge login` once."
        )
    token_dir.mkdir(parents=True, exist_ok=True)
    client = GarminClient(email, password, token_dir=str(token_dir))
    result = client.login()
    if result == "mfa_required":
        raise RuntimeError(
            "Can not perform a fully autonomous GARMIN_TOKEN refresh right now: "
            "MFA is required. Run `paceforge login` once, then this job resumes "
            "autonomously."
        )
    try:
        client.dump_tokens(str(token_dir))
    except Exception:
        logger.debug("Token re-dump after auto-login failed", exc_info=True)
    store.save_token_meta({"login_date": date.today().isoformat()})


def _garmin_email() -> str:
    """The athlete's Garmin login. Env first (Victor's instance sets it); otherwise
    the address the portal login was made with — a friend's instance has no email
    in its env file, only what they typed into "Connect Garmin"."""
    email = os.environ.get("PACEFORGE_GARMIN_EMAIL") or (store.load_token_meta() or {}).get("email")
    if not email:
        raise RuntimeError("No Garmin email — connect Garmin in the portal (Settings) once.")
    return str(email)


def garmin_connect() -> GarminClient:
    email = _garmin_email()
    token_dir = _token_dir()
    _materialize_token(token_dir)
    client = GarminClient.try_reconnect(email, str(token_dir))
    if client is None:
        _auto_login()
        client = GarminClient.try_reconnect(email, str(token_dir))
    if client is None:
        raise RuntimeError(
            "No valid Garmin token — set PACEFORGE_GARMIN_EMAIL/PASSWORD and restart, "
            "or run `paceforge login` once."
        )
    return client


def _ask(prompt: str) -> str:
    """Prompt on stderr so stdout stays clean for capturing the token blob."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()


def login() -> str:
    """Interactive first-time login (handles MFA). Returns a GARMIN_TOKEN blob."""
    email = os.environ.get("PACEFORGE_GARMIN_EMAIL") or _ask("Garmin email: ")
    password = os.environ.get("PACEFORGE_GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    token_dir = _token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    client = GarminClient(email, password, token_dir=str(token_dir))
    if client.login() == "mfa_required":
        client.complete_mfa(_ask("MFA code: ").strip())
    # The refresh token lasts ~a year from this moment; recording the date is the
    # only way to warn before the silent "sync just stopped working" cliff.
    store.save_token_meta({"login_date": date.today().isoformat()})
    return _export_token(token_dir)


def _token_age_days() -> int | None:
    """Days since the last interactive login (None if unknown)."""
    meta = store.load_token_meta() or {}
    login_date = meta.get("login_date")
    if not login_date:
        return None
    try:
        return (date.today() - date.fromisoformat(str(login_date))).days
    except ValueError:
        return None


def export_token() -> str:
    """Return the current on-disk token as a portable blob (no network)."""
    token_dir = _token_dir()
    if not _has_token(token_dir):
        raise RuntimeError("No token on disk to export — run `paceforge sync` (or `login`) first.")
    return _export_token(token_dir)


def refresh_token() -> dict:
    """Refresh the stored Garmin token without user interaction.

    On success returns ``{"result": "ok", "refreshed": True}``. If refresh is
    unnecessary or impossible because MFA/login is required, a non-success
    result is returned with a short reason so the caller/user can react.
    """
    try:
        _auto_login()
        return {"result": "ok", "refreshed": True}
    except RuntimeError as exc:
        return {"result": "failed", "refreshed": False, "error": str(exc)}


# ── Sync / analyse / push ────────────────────────────────────────────


def sync(lookback_days: int = 90, details_limit: int = 40) -> dict:
    """Pull metrics + activities from Garmin into data/*.json (+ recent splits).

    Always writes data/sync-status.json — the UI's only truthful signal of whether
    the numbers on screen are fresh — then re-raises on hard failure.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")
    prev = store.load_sync_status() or {}
    status: dict = {
        "schema": 1,
        "last_attempt": now,
        "last_success": prev.get("last_success"),
        "result": "failed",
        "error": None,
        "endpoints": {},
        "counters": {},
        "token": {"refreshed": False, "age_days": _token_age_days()},
    }
    try:
        client = garmin_connect()
        profile = client.get_fitness_profile(lookback_days=lookback_days)
        status["endpoints"] = client.endpoint_report
        # health_data comes only from /health/import (non-Garmin scales); a fresh
        # Garmin fetch never sets it, so carry the existing value forward or every
        # sync would silently wipe it back to empty.
        existing = store.load_profile()
        if existing is not None:
            profile.health_data = existing.health_data
        store.save_profile(profile)
        history = store.append_daily_history(profile)
        store.save_activities(profile.recent_activities)
        new_details, detail_failures = _sync_details(client, limit=details_limit)
        matched = _match_plan()
        # Write the refreshed token back to disk so the next run reuses it — this is
        # what keeps the token alive between the ~yearly interactive logins.
        try:
            client.dump_tokens(str(_token_dir()))
            status["token"]["refreshed"] = True
        except Exception:
            logger.debug("Token re-dump after sync failed", exc_info=True)
        status["counters"] = {
            "activities": len(profile.recent_activities),
            "new_details": new_details,
            "detail_failures": detail_failures,
            "matched_workouts": matched,
            "history_written": history["written"],
            "history_skip_reason": history["reason"],
        }
        failed = sorted(k for k, v in status["endpoints"].items() if not v.get("ok"))
        partial = bool(failed) or history["reason"] == "skipped_all_null"
        status["result"] = "partial" if partial else "ok"
        status["last_success"] = now
        return {
            "vo2_max": profile.vo2_max,
            "training_readiness": profile.training_readiness,
            "hrv_status": profile.hrv_status,
            "training_status": profile.training_status,
            "activities": len(profile.recent_activities),
            "new_details": new_details,
            "matched_workouts": matched,
            "result": status["result"],
            "failed_endpoints": failed,
        }
    except Exception as e:
        status["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        store.save_sync_status(status)


# ── Non-Garmin health data (e.g. a Hume scale via Apple Health) ────────

# Health Export Kit's additional.body.daily[].values keys -> our BodyComposition field.
_HEALTH_BODY_FIELDS = {
    "bodyMass": "weight_kg",
    "bodyFat": "body_fat_pct",
    "bmi": "bmi",
    "leanBodyMass": "lean_body_mass_kg",
}


def import_health_data(payload: dict, source: str = "apple_health") -> dict:
    """Ingest a Health Export Kit JSON export's body-composition section.

    Hume (or any other Apple-Health-connected scale) writes weight/body-fat/
    BMI into HealthKit; Health Export Kit's ``additional.body.daily`` carries
    it back out (pushed here via a Shortcuts automation, since the app itself
    has no scheduled export). Garmin never sets ``health_data`` (see the
    carry-forward comment in ``sync()``), so this is the only writer. Other
    export categories (sleep/heart/activity) are ignored — Garmin already
    supplies those, at higher fidelity, directly.
    """
    profile = store.load_profile()
    if profile is None:
        raise ValueError("no profile.json yet — run a Garmin sync first")

    bc = profile.health_data.body_composition
    points_by_field = {
        "weight_kg": bc.weight_kg,
        "bmi": bc.bmi,
        "body_fat_pct": bc.body_fat_pct,
        "lean_body_mass_kg": bc.lean_body_mass_kg,
    }
    seen_by_field = {field: {p.date for p in pts} for field, pts in points_by_field.items()}

    written = 0
    daily = ((payload.get("additional") or {}).get("body") or {}).get("daily") or []
    for entry in daily:
        day = str(entry.get("date") or "")[:10]
        if not day:
            continue
        values = entry.get("values") or {}
        for src_key, field in _HEALTH_BODY_FIELDS.items():
            qty = values.get(src_key)
            if qty is None or day in seen_by_field[field]:
                continue
            points_by_field[field].append(HealthDataPoint(date=day, value=float(qty), source=source))
            seen_by_field[field].add(day)
            written += 1

    for points in points_by_field.values():
        points.sort(key=lambda p: p.date)

    if written:
        if source not in profile.health_data.sources:
            profile.health_data.sources.append(source)
        profile.health_data.last_sync = datetime.now(UTC).isoformat(timespec="seconds")
        if bc.weight_kg:
            profile.weight_kg = bc.weight_kg[-1].value
        store.save_profile(profile)

    return {"written": written, "weight_kg": profile.weight_kg}


def log_rpe(activity_id: int | None = None, when: str | None = None, *,
            rpe: int, duration_min: float | None = None, notes: str = "",
            source: str = "cli") -> dict:
    """Record a session RPE (1-10). Keyed by activity_id, or by date for sessions
    the watch didn't record. HR-less strength/HYROX work only counts toward
    training load through these entries (Foster session-RPE)."""
    if not 1 <= int(rpe) <= 10:
        raise RuntimeError("RPE must be 1-10.")
    entry_date = when
    if activity_id is not None:
        act = next((a for a in store.load_activities() if a.activity_id == activity_id), None)
        if act is None:
            raise RuntimeError(f"Unknown activity {activity_id} — sync first.")
        entry_date = entry_date or str(act.start_time)[:10]
        if duration_min is None and act.duration_seconds:
            duration_min = round(act.duration_seconds / 60, 1)
    if entry_date is None:
        raise RuntimeError("Provide an activity_id or a date.")
    if activity_id is None and not duration_min:
        raise RuntimeError("Date-only entries need duration_min to compute load.")
    entry = {"activity_id": activity_id, "date": str(entry_date), "rpe": int(rpe),
             "duration_min": duration_min, "notes": notes or None, "source": source}
    store.upsert_rpe(entry)
    matched = _match_plan()  # copies RPE onto the matched workout
    return {"saved": entry, "entries": len(store.load_rpe()["entries"]),
            "matched_workouts": matched}


def link_activity(activity_id: int, session_id: str | None = None,
                  when: str | None = None) -> dict:
    """Pin a Garmin activity to a plan workout. The matcher applies pins verbatim,
    so sync can never re-assign or drop the link. Target workout by session_id or
    by date (YYYY-MM-DD, must be unambiguous)."""
    if not any(a.activity_id == activity_id for a in store.load_activities()):
        raise RuntimeError(f"Unknown activity {activity_id} — sync first.")
    plan = store.load_plan()
    if not plan:
        raise RuntimeError("No plan stored.")
    wo = _find_workout(plan, session_id=session_id, when=when)
    for wk in plan.weeks:
        for w in wk.workouts:
            if w is not wo and activity_id in w.manual_activity_ids:
                w.manual_activity_ids.remove(activity_id)
    if activity_id in wo.excluded_activity_ids:
        wo.excluded_activity_ids.remove(activity_id)
    if activity_id not in wo.manual_activity_ids:
        wo.manual_activity_ids.append(activity_id)
    store.save_plan(plan)
    _match_plan()
    return {"linked": activity_id, "workout": wo.name, "session_id": wo.session_id,
            "date": str(wo.scheduled_date)}


def unlink_activity(activity_id: int) -> dict:
    """Detach an activity from whatever workout it is linked to (manual or auto)
    and exclude it there, so the next sync cannot silently re-link it."""
    plan = store.load_plan()
    if not plan:
        raise RuntimeError("No plan stored.")
    hits = []
    for wk in plan.weeks:
        for w in wk.workouts:
            if activity_id in w.manual_activity_ids or activity_id in w.matched_activity_ids:
                hits.append(w)
                if activity_id in w.manual_activity_ids:
                    w.manual_activity_ids.remove(activity_id)
                if activity_id not in w.excluded_activity_ids:
                    w.excluded_activity_ids.append(activity_id)
    if not hits:
        raise RuntimeError(f"Activity {activity_id} is not linked to any workout.")
    store.save_plan(plan)
    _match_plan()
    return {"unlinked": activity_id,
            "workouts": [{"name": w.name, "session_id": w.session_id,
                          "date": str(w.scheduled_date)} for w in hits]}


def _find_workout(plan, *, session_id: str | None, when: str | None):
    if session_id:
        for wk in plan.weeks:
            for w in wk.workouts:
                if w.session_id == session_id:
                    return w
        raise RuntimeError(f"No workout with session_id {session_id}.")
    if not when:
        raise RuntimeError("Provide a session_id or a date.")
    hits = [w for wk in plan.weeks for w in wk.workouts
            if str(w.scheduled_date) == when and str(w.workout_type) != "rest"]
    if not hits:
        raise RuntimeError(f"No workout scheduled on {when}.")
    if len(hits) > 1:
        opts = ", ".join(f"{w.session_id} ({w.name})" for w in hits)
        raise RuntimeError(f"Multiple workouts on {when} — use a session_id: {opts}")
    return hits[0]


def brief(when: str | None = None, fmt: str = "text") -> str:
    """Morning brief: readiness, sleep, HRV, body battery + today's scheduled
    session(s). Composed for a phone push notification (Telegram).
    ``fmt="telegram"`` returns Telegram-HTML (bold headers, emoji, pace band)."""
    from datetime import date as _date

    day = _date.fromisoformat(when) if when else _date.today()
    if fmt == "telegram":
        return _brief_telegram(day)
    p = store.load_profile()
    lines = []
    if p:
        vitals = []
        if p.training_readiness is not None:
            vitals.append(f"Readiness {p.training_readiness:.0f}")
        if p.sleep_score is not None:
            sleep = f"Sleep {p.sleep_score}"
            if p.sleep_duration_seconds:
                h, m = divmod(int(p.sleep_duration_seconds // 60), 60)
                sleep += f" ({h}h{m:02d})"
            vitals.append(sleep)
        if p.hrv_status:
            vitals.append(f"HRV {p.hrv_status}")
        if p.body_battery_current is not None:
            vitals.append(f"Battery {p.body_battery_current}")
        if vitals:
            lines.append(" · ".join(vitals))

    plan = store.load_plan()
    todays = [wo for wk in plan.weeks for wo in wk.workouts
              if wo.scheduled_date == day] if plan else []
    sessions = [wo for wo in todays if str(wo.workout_type) != "rest"]
    if sessions:
        for wo in sessions:
            line = f"Today: {wo.name}"
            if wo.estimated_distance_meters:
                line += f" — {wo.estimated_distance_meters / 1000:.1f} km"
            elif wo.estimated_duration_seconds:
                line += f" — {wo.estimated_duration_seconds / 60:.0f} min"
            if wo.briefing and wo.briefing.get("purpose"):
                line += f". {wo.briefing['purpose']}"
            lines.append(line)
    classes = _todays_calendar(day)
    for item in classes:
        line = f"Today: {item.title} ({item.sport})"
        if item.duration_min:
            line += f" — {item.duration_min:.0f} min"
        lines.append(line)
    if not sessions and not classes:
        lines.append("Today: rest day." if todays else "Today: nothing scheduled.")
    return "\n".join(lines) or "No data synced yet."


def _esc_html(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_mss(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _step_pace_band(workout: Workout) -> tuple[float, float] | None:
    """The workout's headline pace band (sec/km): first pace-targeted work step,
    falling back to any pace-targeted step (warmup/cooldown/recovery)."""
    def walk(steps):  # noqa: ANN001
        for st in steps or []:
            yield st
            yield from walk(st.steps)

    fringe = (WorkoutStepType.WARMUP, WorkoutStepType.COOLDOWN,
              WorkoutStepType.RECOVERY, WorkoutStepType.REST)
    paced = [st for st in walk(workout.steps)
             if st.target_type == IntensityTarget.PACE and st.target_low and st.target_high]
    work = [st for st in paced if st.step_type not in fringe]
    st = (work or paced or [None])[0]
    return (st.target_low, st.target_high) if st else None


def _readiness_verdict() -> str | None:
    """Green/amber/red verdict line from data/fitness.json load.readiness_composite."""
    path = store.DATA_DIR / "fitness.json"
    if not path.exists():
        return None
    try:
        rc = json.loads(path.read_text()).get("load", {}).get("readiness_composite") or {}
    except (ValueError, AttributeError):
        return None
    band, score = rc.get("band"), rc.get("score")
    if not band:
        return None
    dot = {"green": "🟢", "moderate": "🟡", "low": "🔴"}.get(band, "⚪")
    score_txt = f" {score:.0f}" if isinstance(score, (int, float)) else ""
    return f"📈 <b>Trend</b> {dot}{score_txt} ({_esc_html(band)})"


def _todays_calendar(day: date) -> list:
    """Scheduled classes/rides/swims for the day — planned sessions like any other."""
    return [i for i in store.load_calendar() if i.date == day]


def _brief_telegram(day: date) -> str:
    """Telegram-HTML morning brief (parse_mode=HTML; the runner prepends the title)."""
    p = store.load_profile()
    lines: list[str] = []
    if p:
        vitals = []
        if p.training_readiness is not None:
            vitals.append(f"❤️ <b>Readiness</b> {p.training_readiness:.0f}")
        if p.sleep_score is not None:
            sleep = f"😴 <b>Sleep</b> {p.sleep_score}"
            if p.sleep_duration_seconds:
                h, m = divmod(int(p.sleep_duration_seconds // 60), 60)
                sleep += f" ({h}h{m:02d})"
            vitals.append(sleep)
        if p.hrv_status:
            vitals.append(f"HRV {_esc_html(p.hrv_status)}")
        if p.body_battery_current is not None:
            vitals.append(f"🔋 <b>Battery</b> {p.body_battery_current}")
        if vitals:
            lines.append(" · ".join(vitals))
    verdict = _readiness_verdict()
    if verdict:
        lines.append(verdict)

    plan = store.load_plan()
    todays = [wo for wk in plan.weeks for wo in wk.workouts
              if wo.scheduled_date == day] if plan else []
    sessions = [wo for wo in todays if str(wo.workout_type) != "rest"]
    if sessions:
        for wo in sessions:
            emoji = "🚴" if wo.sport == "bike" else "🏃"
            parts = []
            if wo.estimated_distance_meters:
                parts.append(f"{wo.estimated_distance_meters / 1000:.1f} km")
            elif wo.estimated_duration_seconds:
                parts.append(f"{wo.estimated_duration_seconds / 60:.0f} min")
            band = _step_pace_band(wo)
            if band:
                parts.append(f"@ {_fmt_mss(band[0])}–{_fmt_mss(band[1])}/km")
            line = f"{emoji} <b>{_esc_html(wo.name)}</b>"
            if parts:
                line += " — " + " ".join(parts)
            lines.append(line)
            if wo.briefing and wo.briefing.get("purpose"):
                lines.append(_esc_html(wo.briefing["purpose"]))
    classes = _todays_calendar(day)
    for item in classes:
        emoji = "🚴" if item.sport.strip().lower() in ("bike", "cycling") else "🏋️"
        line = f"{emoji} <b>{_esc_html(item.title)}</b> ({_esc_html(item.sport)})"
        if item.duration_min:
            line += f" — {item.duration_min:.0f} min"
        lines.append(line)
    if not sessions and not classes:
        lines.append("🏃 Rest day." if todays else "🏃 Nothing scheduled.")
    return "\n".join(lines) or "No data synced yet."


def _match_plan() -> int:
    """Re-match stored activities to the plan and annotate plan-vs-actual compliance.
    Also links completed activities to first-class calendar items (classes)."""
    from paceforge.engine.compliance import annotate_pace, annotate_plan
    from paceforge.engine.matching import match_plan_to_activities

    activities = store.load_activities()
    items = store.load_calendar()
    if items and match_calendar_items(items, activities):
        store.save_calendar(items)
    plan = store.load_plan()
    if not plan:
        return 0
    changed = match_plan_to_activities(plan, activities, rpe_map=store.rpe_by_activity())
    annotate_plan(plan, activities)
    profile = store.load_profile()
    annotate_pace(plan, store.load_all_details(),
                  lt_hr=profile.lactate_threshold_hr if profile else None)
    store.save_plan(plan)
    return changed


def _extract_series(metrics: dict, max_points: int = 120) -> list | None:
    """Downsample Garmin's per-sample metrics into a compact [{t, hr, pace}] series.

    Reads metricDescriptors/activityDetailMetrics; keeps elapsed time, heart rate and
    pace (from speed). Returns None when there's no HR or speed channel (so cardio with
    only HR still yields an HR line, and a run yields both).
    """
    if not isinstance(metrics, dict):
        return None
    descs = metrics.get("metricDescriptors") or []
    rows = metrics.get("activityDetailMetrics") or []
    if not descs or not rows:
        return None
    idx = {d.get("key"): d.get("metricsIndex") for d in descs if isinstance(d, dict)}
    hr_i, sp_i, t_i = (idx.get("directHeartRate"), idx.get("directSpeed"),
                       idx.get("sumElapsedDuration"))
    # Cadence (steps/min, both feet) + stride length — the running-economy channels.
    cad_i = idx.get("directDoubleCadence")
    cad_single = idx.get("directRunCadence") if cad_i is None else None
    str_i = idx.get("directStrideLength")
    if hr_i is None and sp_i is None:
        return None
    step = max(1, -(-len(rows) // max_points))  # ceil division → never exceed max_points
    series = []
    for row in rows[::step]:
        m = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(m, list):
            continue
        def at(i, m=m):
            return m[i] if (i is not None and i < len(m)) else None
        hr, sp, t = at(hr_i), at(sp_i), at(t_i)
        cad = at(cad_i)
        if cad is None and cad_single is not None:  # single-foot cadence → double it
            sc = at(cad_single)
            cad = sc * 2 if sc is not None else None
        stride = at(str_i)  # metres (Garmin) — normalize to cm in the UI
        # speed (m/s) → pace (s/km); ignore near-standstill so pace doesn't blow up.
        pace = round(1000 / sp, 1) if sp and sp > 0.3 else None
        series.append({
            "t": round(t) if t is not None else None,
            "hr": round(hr) if hr is not None else None,
            "pace": pace,
            "cad": round(cad) if cad else None,
            "stride": round(stride, 2) if stride else None,
        })
    return series or None


# Bump when _trim_detail's shape changes so sync re-fetches older stored details.
_DETAIL_VERSION = 3  # v3 adds cadence + stride-length to the time-series


def _trim_detail(detail: dict) -> dict:
    """Reduce a raw ``get_activity_detail`` blob to the lean shape the web charts use."""
    out: dict = {"activity_id": detail.get("activity_id"), "v": _DETAIL_VERSION}

    series = _extract_series(detail.get("metrics"))
    if series:
        out["series"] = series

    splits = detail.get("splits") or {}
    laps = splits.get("lapDTOs") if isinstance(splits, dict) else (
        splits if isinstance(splits, list) else [])
    segs = []
    for i, lap in enumerate(laps or [], start=1):
        if not isinstance(lap, dict):
            continue
        dist = lap.get("distance") or 0
        dur = lap.get("duration") or lap.get("movingDuration") or 0
        segs.append({
            "n": i,
            "distance_m": round(dist, 1) if dist else None,
            "duration_s": round(dur, 1) if dur else None,
            "pace_sec": round(dur / (dist / 1000), 1) if dist and dur else None,
            "avg_hr": lap.get("averageHR"),
            "max_hr": lap.get("maxHR"),
            "elev_gain": lap.get("elevationGain"),
            "avg_cadence": (lap.get("averageRunCadence")
                            or lap.get("averageRunningCadenceInStepsPerMinute")),
        })
    out["splits"] = segs

    hz = detail.get("hr_zones")
    if isinstance(hz, list):
        out["hr_zones"] = [
            {"zone": z.get("zoneNumber"), "secs": z.get("secsInZone"),
             "low": z.get("zoneLowBoundary")}
            for z in hz if isinstance(z, dict)
        ]

    w = detail.get("weather")
    if isinstance(w, dict) and w:
        wt = w.get("weatherTypeDTO") if isinstance(w.get("weatherTypeDTO"), dict) else {}
        out["weather"] = {
            "temp_c": w.get("temp"),
            "feels_c": w.get("apparentTemp"),
            "humidity": w.get("relativeHumidity"),
            "desc": wt.get("desc"),
        }

    # Key presence (even as []) is the "sets were attempted" marker _sync_details
    # keys its targeted refetch on — so a strength session Garmin has no sets for
    # doesn't get its whole detail refetched every sync.
    es = detail.get("exercise_sets")
    if "exercise_sets" in detail:
        sets = []
        for s in (es.get("exerciseSets") if isinstance(es, dict) else None) or []:
            if not isinstance(s, dict) or s.get("setType") == "REST":
                continue
            ex = (s.get("exercises") or [{}])[0]
            weight_g = s.get("weight") or 0
            sets.append({
                "order": s.get("setOrder"),
                "category": ex.get("category"),
                "name": ex.get("name"),
                "reps": s.get("repetitionCount"),
                "weight_kg": round(weight_g / 1000.0, 2) if weight_g else None,
                "duration_s": s.get("duration"),
            })
        out["exercise_sets"] = sets
    return out


def _sync_details(client: GarminClient, limit: int = 40) -> tuple[int, int]:
    """Fetch + store per-activity splits for the recent ``limit`` activities plus any
    matched by the current plan. Incremental (skips stored ids); best-effort per
    activity so one bad fetch never fails the whole sync. Returns (stored, failed).
    """
    recent = store.load_activities()
    ids: list = [a.activity_id for a in recent[:limit]]
    strength_ids = {a.activity_id for a in recent
                    if "strength" in (a.activity_type or "").lower()}
    plan = store.load_plan()
    if plan is not None:
        for wk in plan.weeks:
            for wo in wk.workouts:
                ids.extend(wo.matched_activity_ids or [])

    seen: set = set()
    fetched = 0
    failed = 0
    for aid in ids:
        if aid is None or aid in seen:
            continue
        seen.add(aid)
        # Skip only if the stored detail is already at the current schema version;
        # older details get re-fetched once so the new charts get their time-series.
        # Strength details stored before exercise sets existed (2026-08-10) get one
        # targeted re-fetch — cheaper than a global version bump across all sports.
        if store.has_detail(aid):
            stored = store.load_detail(aid) or {}
            up_to_date = stored.get("v", 0) >= _DETAIL_VERSION
            has_sets = "exercise_sets" in stored or aid not in strength_ids
            if up_to_date and has_sets:
                continue
        try:
            store.save_detail(aid, _trim_detail(_fetch_detail(client, aid)))
            fetched += 1
        except Exception:
            logger.warning("activity detail fetch failed for %s", aid, exc_info=True)
            failed += 1
        # This loop fans out ~6 endpoint calls per activity; pace it so a
        # 40-activity backfill doesn't trip Garmin's rate limiting.
        time.sleep(0.5)
    return fetched, failed


def _fetch_detail(client: GarminClient, activity_id: int) -> dict:
    """One detail fetch with a single retry when Garmin rate-limits (HTTP 429)."""
    try:
        return client.get_activity_detail(activity_id)
    except Exception as e:
        if "429" not in str(e):
            raise
        logger.warning("Rate-limited fetching %s — retrying once in 10s", activity_id)
        time.sleep(10)
        return client.get_activity_detail(activity_id)


def scaffold(goal: dict) -> dict:
    """Build a deterministic baseline plan (correct paces + valid structure) and save it.

    The starting point for the coach loop: Claude personalises the saved plan.json
    on top of this, then re-validates.
    """
    from paceforge.engine.planner import generate_plan
    from paceforge.models.profile import TrainingGoal

    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")
    plan = generate_plan(profile, TrainingGoal.model_validate(goal),
                         hyrox_focus=_hyrox_focus_stations())
    store.save_plan(plan)
    return {
        "name": plan.name,
        "weeks": plan.total_weeks,
        "vdot": plan.vdot,
        "pace_source": plan.pace_source,
        "issues": validate_plan(plan),
    }


def _hyrox_gender() -> str:
    """The athlete's gender as recorded on the imported HYROX results (default M)."""
    p = store._path("hyrox.json")
    if p.exists():
        import json as _json

        try:
            return _json.loads(p.read_text()).get("search_gender") or "M"
        except Exception:
            return "M"
    return "M"


def _hyrox_focus_stations() -> list | None:
    """Weakest two non-running stations from race analysis, for session targeting."""
    analysis = store.load_hyrox_analysis() or {}
    stations = [p["name"] for p in analysis.get("priorities") or []
                if not p.get("is_running") and p.get("name")]
    return stations[:2] or None


def analyze() -> dict:
    """Run the full analytics engine over the stored profile."""
    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")
    return compute_all(profile)


def fitness() -> dict:
    """Fitness 2.0 assessment: running-engine/durability, load/recovery/wellbeing,
    strength/HYROX, and the readiness-gated ranked limiters + LLM-coach contract."""
    from paceforge.engine.compliance import pace_status, weekly_compliance
    from paceforge.engine.curves import compute_pace_curves
    from paceforge.engine.durability import compute_running_metrics
    from paceforge.engine.limiters import rank_limiters
    from paceforge.engine.load import compute_load_recovery
    from paceforge.engine.strength import compute_strength_hyrox

    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")
    activities = store.load_activities()
    details = store.load_all_details()
    from paceforge.engine.form import compute_form
    from paceforge.engine.prognosis import compute_prognosis
    running = compute_running_metrics(activities, details, profile)
    running["pace_curves"] = compute_pace_curves(activities, details)
    form = compute_form(activities, details)
    plan_for_prog = store.load_plan()
    _dist = {"5K": 5.0, "10K": 10.0, "HALF_MARATHON": 21.0975, "MARATHON": 42.195}
    prognosis = compute_prognosis(
        activities, details, profile,
        goal_distance_km=_dist.get(plan_for_prog.goal_type, 21.0975) if plan_for_prog else 21.0975,
        goal_time_sec=plan_for_prog.target_time_seconds if plan_for_prog else None,
        prior_vdot=plan_for_prog.vdot if plan_for_prog else None,
    )
    load = compute_load_recovery(store.load_history(), activities, profile,
                                 rpe_map=store.rpe_by_activity(),
                                 bike_rides=store.load_bike_rides())
    hyrox_data = store.load_hyrox_results()
    gender = _hyrox_gender()
    strength = compute_strength_hyrox(
        hyrox_data, store.load_benchmarks(), profile, activities, details, gender=gender)
    # Effective VO2max (per-run, conditions-adjusted) beats the raw Garmin value
    # as the coach's fitness signal; fall back to the profile figure.
    eff = running.get("effective_vo2max") or {}
    vo2_for_coach = eff.get("current") if eff.get("available") else profile.vo2_max
    limiters = rank_limiters(running, load, strength, profile_vo2max=vo2_for_coach)
    plan = store.load_plan()
    compliance = weekly_compliance(plan, activities, items=store.load_calendar()) if plan else None
    pace_insights = pace_status(plan) if plan and plan.weeks else None

    import json

    from paceforge.engine.insights import daily_insights
    today = date.today()
    todays_type = next((str(wo.workout_type.value) for wk in (plan.weeks if plan else [])
                        for wo in wk.workouts if wo.scheduled_date == today
                        and str(wo.workout_type.value) != "rest"), None)
    try:
        sync_meta = json.loads((store.DATA_DIR / "sync-status.json").read_text())
        last_sync = sync_meta.get("last_success")
    except (OSError, ValueError):
        last_sync = None
    insights = daily_insights(profile.model_dump(), load, running,
                              todays_type=todays_type, last_sync=last_sync)

    return {"running": running, "load": load, "strength": strength,
            "form": form, "prognosis": prognosis, "compliance": compliance,
            "pace_insights": pace_insights, "insights": insights, **limiters}


# ── HYROX race import (results.hyrox.com) ────────────────────────────


def hyrox_search(name: str, *, gender: str = "M", firstname: str = "") -> dict:
    """Search results.hyrox.com for an athlete; write data/hyrox_preview.json.

    Returns a pick-list (no split fetches) the web UI renders so the athlete can
    confirm which races are actually theirs before importing.
    """
    from datetime import datetime

    from paceforge.hyrox.scraper import HyroxScraper

    scraper = HyroxScraper()
    try:
        summaries = scraper.search_preview(name, firstname=firstname, gender=gender)
    finally:
        scraper.close()

    preview = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "query": {"name": name, "gender": gender, "firstname": firstname},
        "results": [
            {
                "name": s.get("name", ""),
                "city": s.get("city", ""),
                "event_date": s.get("city_raw", "") or s.get("city", ""),
                "total_time": s.get("total_time", ""),
                "rank": s.get("rank", ""),
                "athlete_url": s.get("athlete_url", ""),
            }
            for s in summaries
        ],
    }
    store.save_hyrox_preview(preview)
    return preview


def hyrox_import(
    name: str,
    *,
    gender: str = "M",
    firstname: str = "",
    selected_urls: list[str] | None = None,
) -> dict:
    """Fetch full race splits for the chosen athlete URLs; write data/hyrox.json."""
    from paceforge.hyrox.scraper import HyroxScraper, to_cached_dict

    scraper = HyroxScraper()
    try:
        results = scraper.search_athlete(
            name, firstname=firstname, gender=gender, selected_urls=selected_urls
        )
    finally:
        scraper.close()

    store.save_hyrox_results(
        to_cached_dict(results, search_name=name, search_gender=gender)
    )
    return {"imported": len(results), "races": [r.city or r.event_date for r in results]}


def hyrox_import_profile(slug: str, *, gender: str = "M") -> dict:
    """Import every race for a hyresult.com athlete profile → data/hyrox.json.

    hyresult.com is the source of truth: results.hyrox.com's season-overall
    ranking drops races (e.g. Berlin 2026) and reports season-cumulative ranks,
    whereas hyresult has every race with correct per-race Overall + Age-group
    ranks and full splits.
    """
    from paceforge.hyrox.hyresult import HyresultScraper

    scraper = HyresultScraper()
    try:
        results = scraper.fetch_athlete(slug)
    finally:
        scraper.close()

    store.save_hyrox_results({
        "search_name": slug,
        "search_gender": gender,
        "results": [r.model_dump(mode="json") for r in results],
    })
    return {"imported": len(results), "races": [r.city or r.event_date for r in results]}


def validate() -> list[str]:
    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan at data/plan.json.")
    return validate_plan(plan)


def recalibrate(delta_vdot: float, force: bool = False) -> dict:
    """Apply an accepted pace recalibration: shift VDOT, re-derive bands, and
    re-target FUTURE workouts only. Structure never changes (Runna's rule —
    adaptivity must not silently mutate the plan).

    Guards (C13): max ±1 VDOT, max one per 4 weeks, frozen in the final 3
    weeks, blocked while readiness/HRV is down. ``force`` overrides the soft
    guards, never the 3-week freeze.
    """
    from paceforge.engine.vdot import ZONE_KEYS, paces_from_vdot

    plan = store.load_plan()
    if plan is None or not plan.weeks or not plan.vdot:
        raise RuntimeError("No plan with derived paces to recalibrate.")
    if abs(delta_vdot) > 1.0:
        raise RuntimeError("Max ±1.0 VDOT per recalibration.")
    today = date.today()
    if (plan.target_date - today).days < 21:
        raise RuntimeError("Paces are frozen in the final 3 weeks — race what you trained.")
    if plan.last_recalibration and not force:
        days = (today - date.fromisoformat(plan.last_recalibration)).days
        if days < 28:
            raise RuntimeError(
                f"Last recalibration was {days} days ago — max one per 4 weeks "
                "(--force to override)."
            )
    profile = store.load_profile()
    if profile and not force and delta_vdot > 0:
        if (profile.training_readiness or 100) < 40 or \
                (profile.hrv_status or "").upper() == "LOW":
            raise RuntimeError(
                "Readiness/HRV is down — no pace bumps while recovering (--force to override)."
            )

    new_vdot = round(plan.vdot + delta_vdot, 1)
    paces = paces_from_vdot(new_vdot)
    plan.vdot = new_vdot
    plan.easy_pace, plan.marathon_pace = paces.easy_low, paces.marathon
    plan.threshold_pace, plan.interval_pace = paces.threshold, paces.interval
    plan.repetition_pace = paces.repetition
    bands = {k: list(paces.band(k)) for k in ZONE_KEYS}
    if plan.pace_bands and "race" in plan.pace_bands:
        bands["race"] = plan.pace_bands["race"]  # goal pace derives from target time, not VDOT
    plan.pace_bands = bands

    updated = 0

    def _restep(steps) -> None:  # noqa: ANN001
        nonlocal updated
        for s in steps or []:
            if s.pace_key in ZONE_KEYS:
                s.target_low, s.target_high = paces.band(s.pace_key)
                updated += 1
            _restep(s.steps)

    for wk in plan.weeks:
        for wo in wk.workouts:
            if wo.scheduled_date and wo.scheduled_date >= today:
                _restep(wo.steps)

    plan.last_recalibration = today.isoformat()
    plan.adaptation_notes = (
        f"{today}: pace recalibration {delta_vdot:+.1f} VDOT → {new_vdot} "
        f"({updated} future steps re-targeted)"
    )
    store.save_plan(plan)
    return {"vdot": new_vdot, "steps_updated": updated,
            "note": plan.adaptation_notes}


_BRIEFING_LABELS = [
    ("purpose", "Why"), ("structure", "Structure"), ("feel", "Feel"),
    ("if_wrong", "If it goes wrong"), ("cue", "Form cue"), ("venue", "Venue"),
    ("fuel", "Fueling"), ("warmup", "Warm-up"),
]


def _fmt_pace(sec: float | None) -> str:
    if not sec:
        return "—"
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}/km"


def plan_md(path: str = "plan.md") -> str:
    """Render plan.md deterministically from data/plan.json.

    The engine owns this view — the coach skill personalises workout notes in
    the plan itself, then regenerates this file.
    """
    plan = store.load_plan()
    if plan is None or not plan.weeks:
        raise RuntimeError("No plan at data/plan.json.")
    L: list[str] = [f"# {plan.name}", ""]
    goal_line = f"**Goal:** {plan.goal_type} on **{plan.target_date}**"
    if plan.target_time_seconds:
        m, s = divmod(int(plan.target_time_seconds), 60)
        goal_line += f" — target **{m}:{s:02d}**"
    L += [goal_line,
          f"**Weeks:** {plan.total_weeks} | **VDOT:** {plan.vdot or '—'} ({plan.pace_source})",
          ""]
    bands = plan.pace_bands or {}
    keys = ["easy", "marathon", "threshold", "interval", "repetition"]
    if "race" in bands:
        keys.append("race")
    L += ["| " + " | ".join(k.title() for k in keys) + " |", "|" + "---|" * len(keys)]
    row = []
    for k in keys:
        b = bands.get(k)
        row.append(
            f"{_fmt_pace(b[0])}–{_fmt_pace(b[1])}" if b
            else _fmt_pace(getattr(plan, f"{k}_pace", None))
        )
    L += ["| " + " | ".join(row) + " |", ""]
    if plan.rationale:
        L += ["## Rationale", "", plan.rationale, ""]
    if plan.tips:
        L += ["## Coaching notes", ""] + [f"- {t}" for t in plan.tips] + [""]
    L += ["## Week-by-week", "",
          "| Wk | Phase | Focus | Total km | Sessions |", "|---|---|---|---|---|"]
    for wk in plan.weeks:
        sessions = "<br>".join(
            f"**{w.scheduled_date:%a %m/%d}** {w.name}" if w.scheduled_date else w.name
            for w in wk.workouts
        )
        L.append(f"| {wk.week_number} | {wk.phase} | {wk.focus} | "
                 f"{wk.total_distance_km or '—'} | {sessions} |")
    L += ["", "## Session detail", ""]
    for wk in plan.weeks:
        L += [f"### Week {wk.week_number} — {wk.phase} ({wk.total_distance_km or '?'} km)", ""]
        if wk.intro:
            L += [f"_{wk.intro}_", ""]
        for w in wk.workouts:
            when = f"{w.scheduled_date:%a %Y-%m-%d} — " if w.scheduled_date else ""
            km = (w.estimated_distance_meters or 0) / 1000
            mins = (w.estimated_duration_seconds or 0) / 60
            L.append(f"- **{when}{w.name}** ({km:.1f} km, ~{mins:.0f} min)")
            for key, label in _BRIEFING_LABELS:
                val = (w.briefing or {}).get(key)
                if val:
                    L.append(f"  - **{label}:** {val}")
            if w.notes:
                L.append(f"  - **Coach's note:** {w.notes}")
        L.append("")
    md = "\n".join(L).rstrip() + "\n"
    Path(path).write_text(md)
    return md


def _upcoming_weeks(plan: TrainingPlan) -> list[TrainingWeek]:
    """Plan weeks with at least one workout scheduled today or later, in order."""
    today = date.today()
    return [
        wk for wk in plan.weeks
        if any(w.scheduled_date and w.scheduled_date >= today for w in wk.workouts)
    ]


def _select_week(plan: TrainingPlan, week: int | None) -> TrainingWeek:
    if week is not None:
        for wk in plan.weeks:
            if wk.week_number == week:
                return wk
        raise RuntimeError(f"Week {week} not in plan.")
    upcoming = _upcoming_weeks(plan)
    return upcoming[0] if upcoming else plan.weeks[0]


def _plan_paces(plan: TrainingPlan) -> dict:
    return {
        "easy_pace": plan.easy_pace,
        "marathon_pace": plan.marathon_pace,
        "threshold_pace": plan.threshold_pace,
        "interval_pace": plan.interval_pace,
    }


def push(week: int | None = None, dry_run: bool = False) -> dict:
    """Push one plan week's workouts to Garmin (validates the plan first)."""
    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan at data/plan.json.")
    issues = validate_plan(plan)
    if issues:
        raise RuntimeError("Plan failed validation — fix before pushing:\n- " + "\n- ".join(issues))
    wk = _select_week(plan, week)
    workouts = [w for w in wk.workouts if w.workout_type.value != "rest"]
    summary = [
        {"name": w.name, "date": str(w.scheduled_date), "type": w.workout_type.value}
        for w in workouts
    ]
    if dry_run:
        return {"week": wk.week_number, "dry_run": True, "workouts": summary}
    client = garmin_connect()
    result = client.push_plan_week(workouts, plan_paces=_plan_paces(plan),
                                   pace_bands=plan.pace_bands)
    store.save_plan(plan)  # persist garmin_workout_id for delete-by-id on re-push
    return {"week": wk.week_number, "pushed": len(result["pushed"]),
            "failed": result["failed"], "workouts": summary,
            "uploads": result["pushed"]}


def garmin_reconcile(client: GarminClient | None = None) -> dict:
    """Make the Garmin calendar from today forward exactly mirror the accepted plan.

    Three passes: (a) delete stale scheduled copies of completed past workouts,
    (b) push/refresh current + next 2 weeks (idempotent — push_plan_week deletes
    by stored ``garmin_workout_id`` before re-uploading), (c) delete orphans:
    scheduled entries >= today whose id no plan workout owns. Same no-sport-filter
    sweep as garmin_clear_calendar — we push running AND bike workouts, so every
    scheduled workout the plan doesn't own is fair game.
    """
    plan = store.load_plan()
    if plan is not None:
        if not plan.accepted:
            raise RuntimeError("Plan not accepted — refusing to reconcile.")
        # Same gate as push(): a plan that fails validation must not reach the watch,
        # and runner's job_plan accepts a freshly scaffolded plan without checking.
        issues = validate_plan(plan)
        if issues:
            raise RuntimeError("Plan failed validation — fix before pushing:\n- "
                               + "\n- ".join(issues))
    client = client or garmin_connect()
    cal_items = store.load_calendar()

    # (a) Completed past workouts no longer need their scheduled Garmin copy.
    today = date.today()
    stale_deleted = 0
    delete_failed = 0
    plan_weeks = plan.weeks if plan else []
    for wk in plan_weeks:
        for w in wk.workouts:
            if (w.garmin_workout_id and w.completed
                    and w.scheduled_date and w.scheduled_date < today):
                # Keep the id on failure so tomorrow's reconcile retries the delete.
                try:
                    client.delete_workout(w.garmin_workout_id)
                    w.garmin_workout_id = None
                    stale_deleted += 1
                except Exception:
                    logger.warning("Reconcile: stale delete failed for Garmin id %s",
                                   w.garmin_workout_id, exc_info=True)
                    delete_failed += 1

    # (b) Push/refresh the upcoming window: plan weeks + calendar items (21d).
    weeks = _upcoming_weeks(plan)[:3] if plan else []  # current + next 2
    pushed = 0
    failed: list[dict] = []
    for wk in weeks:
        workouts = [w for w in wk.workouts if w.workout_type.value != "rest"]
        result = client.push_plan_week(workouts, plan_paces=_plan_paces(plan),
                                       pace_bands=plan.pace_bands)
        pushed += len(result["pushed"])
        failed += result["failed"]
    upcoming_items = [i for i in cal_items
                      if today <= i.date <= today + timedelta(days=21)]
    if upcoming_items:
        bridged = [(_item_to_workout(i), i) for i in upcoming_items]
        result = client.push_plan_week([w for w, _ in bridged])
        pushed += len(result["pushed"])
        failed += result["failed"]
        for w, i in bridged:
            i.garmin_workout_id = w.garmin_workout_id

    # (c) Orphans: anything scheduled >= today that neither the plan nor the
    # calendar owns now.
    owned = {int(w.garmin_workout_id) for wk in plan_weeks for w in wk.workouts
             if w.garmin_workout_id}
    owned |= {int(i.garmin_workout_id) for i in cal_items if i.garmin_workout_id}
    orphans_deleted = 0
    seen: set[int] = set()
    for s in client.get_scheduled_workouts(days_ahead=400):
        wid = s.get("workout_id")
        when = str(s.get("scheduled_date", ""))[:10]
        if not wid or when < today.isoformat() or int(wid) in seen:
            continue
        seen.add(int(wid))
        if int(wid) in owned:
            continue
        try:
            client.delete_workout(int(wid))
            orphans_deleted += 1
        except Exception:
            logger.warning("Reconcile: orphan delete failed for Garmin id %s", wid, exc_info=True)
            delete_failed += 1

    if plan:
        store.save_plan(plan)  # persist garmin_workout_id changes
    store.save_calendar(cal_items)
    # Persist the outcome for the portal — reconcile runs from cron, so these
    # counts otherwise die in the journal.
    status = store.load_sync_status() or {}
    status["push"] = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pushed": pushed,
        "failed": len(failed),
        "stale_deleted": stale_deleted,
        "orphans_deleted": orphans_deleted,
    }
    store.save_sync_status(status)
    return {"weeks": [wk.week_number for wk in weeks], "pushed": pushed,
            "stale_deleted": stale_deleted, "orphans_deleted": orphans_deleted,
            "delete_failed": delete_failed, "failed": failed}


def autosync(client: GarminClient | None = None) -> dict:
    """Daily cron entrypoint — the plan owns the calendar; alias for garmin_reconcile."""
    return garmin_reconcile(client=client)


def garmin_delete(client: GarminClient | None = None) -> dict:
    """Delete every pushed workout of the current plan from the Garmin calendar.

    Clears each ``garmin_workout_id`` and persists the plan. Used by the
    "Delete from Garmin" button and the rebuild's clean-slate step.
    """
    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan at data/plan.json.")
    client = client or garmin_connect()
    deleted = 0
    failed = 0
    for week in plan.weeks:
        for w in week.workouts:
            if w.garmin_workout_id:
                # Keep the id on failure so a re-run retries the delete.
                try:
                    client.delete_workout(w.garmin_workout_id)
                    w.garmin_workout_id = None
                    deleted += 1
                except Exception:
                    logger.warning("garmin_delete: failed for Garmin id %s",
                                   w.garmin_workout_id, exc_info=True)
                    failed += 1
    if deleted:
        store.save_plan(plan)
    return {"deleted": deleted, "failed": failed}


def garmin_clear_calendar(
    days_ahead: int = 400, dry_run: bool = False, client: GarminClient | None = None,
) -> dict:
    """Remove scheduled workouts from the Garmin calendar from today onwards.

    Deletes every scheduled workout dated >= today (deduped by workout id); past
    entries are left untouched. With dry_run, returns the list that *would* be
    deleted without touching Garmin. Also clears matching future
    ``garmin_workout_id``s in plan.json so a fresh push starts clean.
    """
    client = client or garmin_connect()
    today = date.today().isoformat()
    scheduled = client.get_scheduled_workouts(days_ahead=days_ahead)

    seen: set[int] = set()
    targets: list[dict] = []
    for s in scheduled:
        wid = s.get("workout_id")
        when = str(s.get("scheduled_date", ""))[:10]
        if not wid or when < today or int(wid) in seen:
            continue
        seen.add(int(wid))
        targets.append({"id": int(wid), "date": when, "name": s.get("name", "Workout")})

    if dry_run:
        return {"dry_run": True, "from": today, "count": len(targets), "workouts": targets}

    failed_ids: set[int] = set()
    for t in targets:
        try:
            client.delete_workout(t["id"])
        except Exception:
            logger.warning("clear_calendar: delete failed for Garmin id %s", t["id"], exc_info=True)
            failed_ids.add(t["id"])

    plan = store.load_plan()
    if plan:
        changed = False
        for week in plan.weeks:
            for w in week.workouts:
                # Keep ids whose delete failed — clearing them would orphan the Garmin copy.
                if (w.garmin_workout_id and int(w.garmin_workout_id) not in failed_ids
                        and w.scheduled_date and w.scheduled_date.isoformat() >= today):
                    w.garmin_workout_id = None
                    changed = True
        if changed:
            store.save_plan(plan)

    return {"deleted": len(targets) - len(failed_ids), "failed": len(failed_ids), "from": today}


def calendar_edit(
    session_id: str, action: str, new_date: str | None = None,
    client: GarminClient | None = None,
) -> dict:
    """Reschedule or delete one session from the portal calendar and sync Garmin.

    ``action="reschedule"`` moves the workout's ``scheduled_date`` to *new_date*
    and re-pushes it (deleting the old Garmin entry by id); ``action="delete"``
    removes it from the plan and from the Garmin calendar. Persists the plan.
    """
    # The id may name a plan workout OR a first-class calendar item.
    items = store.load_calendar()
    item = next((i for i in items if i.item_id == session_id), None)
    if item is not None:
        return _calendar_edit_item(items, item, action, new_date, client)

    plan = store.load_plan()
    if plan is None:
        raise RuntimeError(f"No session {session_id} — no plan and no such calendar item.")

    found: tuple[object, Workout] | None = None
    for week in plan.weeks:
        for w in week.workouts:
            if w.session_id == session_id:
                found = (week, w)
                break
        if found:
            break
    if found is None:
        raise RuntimeError(f"No session {session_id} in the plan or calendar.")
    week, workout = found

    client = client or garmin_connect()
    if action == "delete":
        if workout.garmin_workout_id:
            try:
                client.delete_workout(workout.garmin_workout_id)
            except Exception as e:
                raise RuntimeError(
                    f"Garmin refused to delete workout {workout.garmin_workout_id} — "
                    "session kept in the plan; retry when Garmin is reachable."
                ) from e
        week.workouts.remove(workout)
    elif action == "reschedule":
        if not new_date:
            raise ValueError("reschedule needs new_date (YYYY-MM-DD).")
        workout.scheduled_date = date.fromisoformat(new_date)
        paces = {
            "easy_pace": plan.easy_pace,
            "marathon_pace": plan.marathon_pace,
            "threshold_pace": plan.threshold_pace,
            "interval_pace": plan.interval_pace,
        }
        # push_plan_week deletes the old Garmin entry by id, re-pushes on the new
        # date, and stamps the new garmin_workout_id back onto the workout.
        client.push_plan_week([workout], plan_paces=paces)
    else:
        raise ValueError(f"Unknown calendar action {action!r}.")

    issues = validate_plan(plan)
    store.save_plan(plan)
    return {"action": action, "session_id": session_id, "validation_issues": issues}


def _calendar_edit_item(items: list, item, action: str, new_date: str | None,
                        client: GarminClient | None) -> dict:
    """Reschedule/delete a first-class calendar item + mirror it on Garmin."""
    client = client or garmin_connect()
    if action == "delete":
        if item.garmin_workout_id:
            try:
                client.delete_workout(item.garmin_workout_id)
            except Exception as e:
                raise RuntimeError(
                    f"Garmin refused to delete workout {item.garmin_workout_id} — "
                    "item kept; retry when Garmin is reachable."
                ) from e
        items.remove(item)
    elif action == "reschedule":
        if not new_date:
            raise ValueError("reschedule needs new_date (YYYY-MM-DD).")
        item.date = date.fromisoformat(new_date)
        w = _item_to_workout(item)
        client.push_plan_week([w])
        item.garmin_workout_id = w.garmin_workout_id
    else:
        raise ValueError(f"Unknown calendar action {action!r}.")
    store.save_calendar(items)
    return {"action": action, "session_id": item.item_id, "validation_issues": []}


_EXTRA_SESSION_TYPE = {"hyrox": WorkoutType.HYROX_MIXED}
_MAX_REPEAT_WEEKS = 52
# A class is a class: anything outside this is a typo or a bad form post, and a
# negative value silently writes a workout with a negative duration.
_MIN_SESSION_MINUTES = 5
_MAX_SESSION_MINUTES = 480


# Garmin activity-type families for matching a calendar item to a completed
# activity by date. Generic sports (Cardio/other) accept any non-running type.
_SPORT_ACTIVITY_TYPES = {
    "bike": {"cycling", "road_biking", "indoor_cycling", "virtual_ride", "mountain_biking",
             "gravel_cycling", "cycling_indoor"},
    "swim": {"lap_swimming", "open_water_swimming", "swimming"},
}
_RUNNING_TYPES = {"running", "treadmill_running", "trail_running", "track_running",
                  "indoor_running", "virtual_run"}


def match_calendar_items(items: list, activities: list[dict]) -> int:
    """Link completed Garmin activities to scheduled calendar items (same date,
    compatible sport). Never steals an activity already claimed by another item.
    Returns how many items changed."""
    claimed = {aid for i in items for aid in i.matched_activity_ids}
    changed = 0
    for item in items:
        if item.completed:
            continue
        fam = _SPORT_ACTIVITY_TYPES.get(item.sport.strip().lower())
        for a in activities:
            get = (lambda k, _a=a: _a.get(k)) if isinstance(a, dict) else                   (lambda k, _a=a: getattr(_a, k, None))
            aid = str(get("activity_id") or "")
            when = str(get("start_time") or "")[:10]
            atype = str(get("activity_type") or "").lower()
            if not aid or aid in claimed or when != item.date.isoformat():
                continue
            if fam is not None:
                if atype not in fam:
                    continue
            elif atype in _RUNNING_TYPES:
                continue   # generic classes never claim runs — those belong to the plan
            item.matched_activity_ids.append(aid)
            item.completed = True
            claimed.add(aid)
            changed += 1
            break
    return changed


def _item_to_workout(item) -> Workout:
    """Bridge a ScheduledItem to the Workout shape the Garmin push code speaks."""
    workout_type = _EXTRA_SESSION_TYPE.get(item.sport.strip().lower(),
                                           WorkoutType.CROSS_TRAINING)
    w = Workout(
        name=item.title or f"{item.sport.strip().title()} Class",
        workout_type=workout_type,
        scheduled_date=item.date,
        estimated_duration_seconds=float(item.duration_min) * 60,
        estimated_distance_meters=(item.distance_km or 0) * 1000 or None,
        notes=item.notes,
    )
    w.garmin_workout_id = item.garmin_workout_id
    return w


def add_session(session_date: str, sport: str, minutes: int, name: str = "",
                repeat_weeks: int = 1) -> dict:
    """Schedule a class/session as a first-class calendar item (data/calendar.json).

    2026-08-10 decoupling: this no longer creates or touches any TrainingPlan —
    the calendar is the athlete's whole week; the running plan merely contributes
    to the same view. ``repeat_weeks`` schedules the item weekly (1 = once).
    """
    from datetime import timedelta

    from paceforge.models.calendar import ScheduledItem

    start = date.fromisoformat(session_date)
    title = (name.strip() or f"{sport.strip().title()} Class")[:120]  # Garmin name cap
    count = min(max(int(repeat_weeks), 1), _MAX_REPEAT_WEEKS)
    duration = min(max(int(minutes), _MIN_SESSION_MINUTES), _MAX_SESSION_MINUTES)

    items = store.load_calendar()
    new_items = [
        ScheduledItem(date=start + timedelta(weeks=i), sport=sport.strip() or "Cardio",
                      title=title, duration_min=duration)
        for i in range(count)
    ]
    items.extend(new_items)
    match_calendar_items(items, store.load_activities())
    store.save_calendar(items)
    return {"session_ids": [i.item_id for i in new_items], "scheduled_date": session_date,
            "repeat_weeks": count, "sport": sport}


_PROPOSAL_FIELDS = {"scheduled_date", "name", "notes"}   # what a proposal may touch


def _load_proposals() -> list[dict]:
    p = store.DATA_DIR / "pending-changes.json"
    try:
        return json.loads(p.read_text()) or []
    except (OSError, json.JSONDecodeError):
        return []


def _save_proposals(items: list[dict]) -> None:
    store._write(store.DATA_DIR / "pending-changes.json", json.dumps(items, indent=1))


def resolve_proposal(proposal_id: str, action: str) -> dict:
    """Coach proposes, athlete disposes: apply or reject one pending change set.

    Proposals live in data/pending-changes.json (written by the coach skill —
    per-session field diffs only, never silent edits). Apply mutates plan.json,
    re-validates, and leaves the Garmin push to the caller's reconcile.
    """
    items = _load_proposals()
    prop = next((x for x in items if x.get("id") == proposal_id), None)
    if prop is None:
        raise RuntimeError(f"No pending proposal {proposal_id!r}.")
    items.remove(prop)
    if action == "reject":
        _save_proposals(items)
        return {"action": "rejected", "id": proposal_id}
    if action != "apply":
        raise ValueError(f"Unknown proposal action {action!r}")

    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan to apply the proposal to.")
    by_id = {w.session_id: w for wk in plan.weeks for w in wk.workouts}
    applied = 0
    for ch in prop.get("changes", []):
        w = by_id.get(ch.get("session_id"))
        field = ch.get("field")
        if w is None or field not in _PROPOSAL_FIELDS:
            continue
        value = ch.get("to")
        if field == "scheduled_date":
            value = date.fromisoformat(str(value))
        setattr(w, field, value)
        applied += 1
    issues = validate_plan(plan)
    if issues:
        # A proposal must not corrupt the plan — put it back and refuse.
        items.append(prop)
        _save_proposals(items)
        raise RuntimeError(f"Proposal breaks validation: {issues[:3]}")
    store.save_plan(plan)
    _save_proposals(items)
    return {"action": "applied", "id": proposal_id, "applied_changes": applied}


def _scale_step(step, factor: float) -> None:
    """Scale one workout step (and its children) in place."""
    if step.duration_seconds:
        step.duration_seconds = max(60.0, round(step.duration_seconds * factor))
    if step.distance_meters:
        step.distance_meters = max(200.0, round(step.distance_meters * factor, -1))
    for sub in (step.steps or []):
        _scale_step(sub, factor)


def adjust_today(mode: str, minutes: int | None = None) -> dict:
    """Same-day workout rewrite: "not feeling 100%" / "only have N minutes" /
    "sick" — compress or downgrade TODAY's session in place (same session_id,
    same Garmin id so the push replaces it on the watch) while keeping the
    stimulus intent. Reductions only, so no ramp/validation risk.
    """
    from paceforge.models.plan import TrainingPurpose, WorkoutStep, WorkoutStepType

    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan — nothing scheduled to adjust.")
    today = date.today()
    workout = next((w for wk in plan.weeks for w in wk.workouts
                    if w.scheduled_date == today
                    and w.workout_type.value != "rest" and not w.completed), None)
    if workout is None:
        raise RuntimeError("No uncompleted session scheduled today.")

    original_name = workout.name
    est_min = (workout.estimated_duration_seconds or 3600) / 60

    if mode == "sick":
        # Keep the calendar slot but make it optional, untargeted movement.
        workout.steps = [WorkoutStep(
            step_type=WorkoutStepType.ACTIVE, duration_seconds=1200.0,
            description="20min very easy — or skip entirely, full rest is the "
                        "better call if symptoms are below the neck.",
        )]
        workout.workout_type = WorkoutType.RECOVERY
        workout.purpose = TrainingPurpose.RECOVERY
        workout.estimated_duration_seconds = 1200.0
        workout.estimated_distance_meters = None
        summary = "replaced with 20min optional recovery"
    elif mode == "time":
        if not minutes or minutes < 15:
            raise ValueError("mode=time needs minutes >= 15")
        factor = min(1.0, (minutes * 60) / (workout.estimated_duration_seconds or 3600))
        if factor >= 0.98:
            return {"adjusted": False, "reason": "session already fits", "name": original_name}
        for s in workout.steps:
            _scale_step(s, factor)
        if workout.estimated_duration_seconds:
            workout.estimated_duration_seconds = round(workout.estimated_duration_seconds * factor)
        if workout.estimated_distance_meters:
            workout.estimated_distance_meters = round(workout.estimated_distance_meters * factor, -1)
        summary = f"compressed ~{round(factor * 100)}% to fit {minutes} min"
    elif mode == "tired":
        factor = 0.65
        for s in workout.steps:
            _scale_step(s, factor)
        if workout.estimated_duration_seconds:
            workout.estimated_duration_seconds = round(workout.estimated_duration_seconds * factor)
        if workout.estimated_distance_meters:
            workout.estimated_distance_meters = round(workout.estimated_distance_meters * factor, -1)
        summary = "reduced ~35% — same shape, lighter dose"
    else:
        raise ValueError(f"Unknown adjust mode {mode!r}")

    if not workout.name.endswith("(adjusted)"):
        workout.name = (workout.name + " (adjusted)")[:120]
    workout.notes = (f"[Adjusted same-day: {summary} — was '{original_name}', "
                     f"~{est_min:.0f}min] " + (workout.notes or "")).strip()

    # Replace on the watch immediately (same garmin_workout_id → delete+re-push).
    pushed = False
    try:
        client = garmin_connect()
        client.push_plan_week([workout], plan_paces=_plan_paces(plan),
                              pace_bands=plan.pace_bands)
        pushed = True
    except Exception:
        logger.warning("adjust_today: Garmin push failed — reconcile will retry",
                       exc_info=True)
    store.save_plan(plan)
    return {"adjusted": True, "mode": mode, "summary": summary,
            "name": workout.name, "pushed": pushed}


def adapt(dry_run: bool = False) -> dict:
    """Deterministic plan adaptation: reflow missed quality sessions and
    readiness-gate imminent hard work. The coach remains the judgement layer;
    this gives it (and the athlete) a safe, rule-based lever."""
    from datetime import timedelta

    from paceforge.engine.adaptation import (
        hold_back_progression,
        readiness_gate,
        reflow_missed_sessions,
    )
    from paceforge.engine.load import compute_load_recovery

    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan at data/plan.json.")
    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")

    activities = store.load_activities()
    load = compute_load_recovery(store.load_history(), activities, profile,
                                 rpe_map=store.rpe_by_activity(),
                                 bike_rides=store.load_bike_rides())
    readiness = load.get("readiness_composite") or {}
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_rpe = max(
        (e["rpe"] for e in store.load_rpe()["entries"]
         if str(e.get("date")) == yesterday and e.get("rpe")),
        default=None,
    )

    changes = reflow_missed_sessions(plan)
    changes += readiness_gate(plan, readiness, yesterday_rpe=yesterday_rpe)
    changes += hold_back_progression(plan)
    issues = validate_plan(plan)
    if not dry_run and changes and not issues:
        store.save_plan(plan)
    return {
        "dry_run": dry_run,
        "changes": changes,
        "saved": bool(changes and not issues and not dry_run),
        "validation_issues": issues,
        "readiness": {"score": readiness.get("score"), "band": readiness.get("band")},
        "yesterday_rpe": yesterday_rpe,
    }


def status() -> dict:
    profile = store.load_profile()
    plan = store.load_plan()
    return {
        "profile": None if not profile else {
            "vo2_max": profile.vo2_max,
            "training_readiness": profile.training_readiness,
            "hrv_status": profile.hrv_status,
            "activities": len(profile.recent_activities),
            "profile_date": str(profile.profile_date),
        },
        "plan": None if not plan else {
            "name": plan.name,
            "goal": plan.goal_type,
            "target_date": str(plan.target_date),
            "weeks": plan.total_weeks,
            "accepted": plan.accepted,
        },
        "sync": store.load_sync_status(),
    }
