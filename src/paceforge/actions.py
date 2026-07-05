"""Core actions shared by the CLI and the MCP server.

One module, two entrypoints — ``cli.py`` and ``mcp_server.py`` are thin wrappers
over these functions. All state lives in ``data/*.json`` via :mod:`paceforge.store`.

Garmin auth: a one-time interactive ``login()`` dumps a ~1-year token to
``PACEFORGE_GARMIN_TOKEN_DIR`` and returns a base64 blob to store as the
``GARMIN_TOKEN`` secret. Headless runs (CI) rematerialize that blob and reconnect
with no password and no MFA.
"""

from __future__ import annotations

import base64
import getpass
import io
import logging
import os
import sys
import tarfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from paceforge import store
from paceforge.engine.analytics import compute_all
from paceforge.engine.validate import validate_plan
from paceforge.garmin.client import GarminClient
from paceforge.models.plan import TrainingPlan, TrainingWeek

logger = logging.getLogger(__name__)

# ── Garmin auth ──────────────────────────────────────────────────────


def _token_dir() -> Path:
    return Path(os.getenv("PACEFORGE_GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()


def _has_token(token_dir: Path) -> bool:
    return token_dir.exists() and any(token_dir.iterdir())


def _materialize_token(token_dir: Path) -> None:
    """Unpack the GARMIN_TOKEN secret into the token dir for headless runs."""
    blob = os.getenv("GARMIN_TOKEN")
    if not blob or _has_token(token_dir):
        return
    token_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(blob)), mode="r:gz") as tar:
        tar.extractall(token_dir)  # noqa: S202 — our own token archive


def _export_token(token_dir: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in sorted(token_dir.iterdir()):
            if f.is_file():
                tar.add(f, arcname=f.name)
    return base64.b64encode(buf.getvalue()).decode()


def garmin_connect() -> GarminClient:
    email = os.environ["PACEFORGE_GARMIN_EMAIL"]
    token_dir = _token_dir()
    _materialize_token(token_dir)
    client = GarminClient.try_reconnect(email, str(token_dir))
    if client is None:
        raise RuntimeError("No valid Garmin token — run `paceforge login` once to create one.")
    return client


def _ask(prompt: str) -> str:
    """Prompt on stderr so stdout stays clean for capturing the token blob."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()


def login() -> str:
    """Interactive first-time login (handles MFA). Returns the GARMIN_TOKEN blob."""
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
    """Return the current on-disk token as a GARMIN_TOKEN blob (no network)."""
    token_dir = _token_dir()
    if not _has_token(token_dir):
        raise RuntimeError("No token on disk to export — run `paceforge sync` (or `login`) first.")
    return _export_token(token_dir)


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
        store.save_profile(profile)
        history = store.append_daily_history(profile)
        store.save_activities(profile.recent_activities)
        new_details, detail_failures = _sync_details(client, limit=details_limit)
        matched = _match_plan()
        # Write the refreshed token back to disk so the workflow can persist it to
        # the GARMIN_TOKEN secret — keeps the headless token from going stale.
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


def _match_plan() -> int:
    """Re-match stored activities to the plan and annotate plan-vs-actual compliance."""
    from paceforge.engine.compliance import annotate_plan
    from paceforge.engine.matching import match_plan_to_activities

    plan = store.load_plan()
    if not plan:
        return 0
    activities = store.load_activities()
    changed = match_plan_to_activities(plan, activities, rpe_map=store.rpe_by_activity())
    annotate_plan(plan, activities)
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
_DETAIL_VERSION = 4  # v4 adds typed_splits (run/station/roxzone auto-segmentation)


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

    # Typed splits: keep the run/walk/stand typing so engine/segments.py can slice
    # a recorded HYROX sim into run/station/roxzone without any manual tagging.
    typed = detail.get("typed_splits") or {}
    tsplits = typed.get("splits") if isinstance(typed, dict) else (
        typed if isinstance(typed, list) else [])
    tsegs = []
    for ts in tsplits or []:
        if not isinstance(ts, dict):
            continue
        dist = ts.get("distance") or 0
        dur = ts.get("duration") or ts.get("movingDuration") or 0
        tsegs.append({
            "type": ts.get("type") or ts.get("splitType"),
            "distance_m": round(dist, 1) if dist else None,
            "duration_s": round(dur, 1) if dur else None,
            "avg_hr": ts.get("averageHR"),
        })
    if tsegs:
        out["typed_splits"] = tsegs

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
    return out


def _sync_details(client: GarminClient, limit: int = 40) -> tuple[int, int]:
    """Fetch + store per-activity splits for the recent ``limit`` activities plus any
    matched by the current plan. Incremental (skips stored ids); best-effort per
    activity so one bad fetch never fails the whole sync. Returns (stored, failed).
    """
    ids: list = [a.activity_id for a in store.load_activities()[:limit]]
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
        if store.has_detail(aid) and (store.load_detail(aid) or {}).get("v", 0) >= _DETAIL_VERSION:
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
    from paceforge.engine.compliance import weekly_compliance
    from paceforge.engine.curves import compute_pace_curves
    from paceforge.engine.durability import compute_running_metrics
    from paceforge.engine.limiters import rank_limiters
    from paceforge.engine.load import compute_load_recovery
    from paceforge.engine.segments import segment_hyrox_activities
    from paceforge.engine.strength import compute_strength_hyrox

    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")
    activities = store.load_activities()
    details = store.load_all_details()
    running = compute_running_metrics(activities, details, profile)
    running["pace_curves"] = compute_pace_curves(activities, details)
    load = compute_load_recovery(store.load_history(), activities, profile,
                                 rpe_map=store.rpe_by_activity())
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
    compliance = weekly_compliance(plan, activities) if plan else None
    hyrox_segments = segment_hyrox_activities(activities, details)
    return {"running": running, "load": load, "strength": strength,
            "compliance": compliance, "hyrox_segments": hyrox_segments, **limiters}


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


def _select_week(plan: TrainingPlan, week: int | None) -> TrainingWeek:
    if week is not None:
        for wk in plan.weeks:
            if wk.week_number == week:
                return wk
        raise RuntimeError(f"Week {week} not in plan.")
    today = date.today()
    upcoming = [
        wk for wk in plan.weeks
        if any(w.scheduled_date and w.scheduled_date >= today for w in wk.workouts)
    ]
    return upcoming[0] if upcoming else plan.weeks[0]


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
    paces = {
        "easy_pace": plan.easy_pace,
        "marathon_pace": plan.marathon_pace,
        "threshold_pace": plan.threshold_pace,
        "interval_pace": plan.interval_pace,
    }
    client = garmin_connect()
    result = client.push_plan_week(workouts, plan_paces=paces)
    store.save_plan(plan)  # persist garmin_workout_id for delete-by-id on re-push
    return {"week": wk.week_number, "pushed": len(result["pushed"]),
            "failed": result["failed"], "workouts": summary,
            "uploads": result["pushed"]}


def adapt(dry_run: bool = False) -> dict:
    """Deterministic plan adaptation: reflow missed quality sessions and
    readiness-gate imminent hard work. The coach remains the judgement layer;
    this gives it (and the athlete) a safe, rule-based lever."""
    from datetime import timedelta

    from paceforge.engine.adaptation import readiness_gate, reflow_missed_sessions
    from paceforge.engine.load import compute_load_recovery

    plan = store.load_plan()
    if plan is None:
        raise RuntimeError("No plan at data/plan.json.")
    profile = store.load_profile()
    if profile is None:
        raise RuntimeError("No profile — run `paceforge sync` first.")

    activities = store.load_activities()
    load = compute_load_recovery(store.load_history(), activities, profile,
                                 rpe_map=store.rpe_by_activity())
    readiness = load.get("readiness_composite") or {}
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_rpe = max(
        (e["rpe"] for e in store.load_rpe()["entries"]
         if str(e.get("date")) == yesterday and e.get("rpe")),
        default=None,
    )

    changes = reflow_missed_sessions(plan)
    changes += readiness_gate(plan, readiness, yesterday_rpe=yesterday_rpe)
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
