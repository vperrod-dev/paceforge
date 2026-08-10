"""Thin wrapper around python-garminconnect for PaceForge."""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin
from garminconnect.workout import (
    ConditionType,
    ExecutableStep,
    RepeatGroup,
    RunningWorkout,
    StepType,
    TargetType,
    WorkoutSegment,
    create_repeat_group,
)

from paceforge.engine.vdot import normalize_lt_speed as _normalize_lt_speed
from paceforge.models.plan import (
    IntensityTarget,
    Workout,
    WorkoutStep,
    WorkoutStepType,
)
from paceforge.models.profile import (
    HRZone,
    PersonalRecord,
    RacePrediction,
    RecentActivity,
    UserFitnessProfile,
)

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_DIR = "~/.garminconnect"   # noqa: S105 — a directory path, not a secret

# Structured-workout sport types. Running is the default; HYROX bricks and
# station days go up as fitness_equipment (Garmin's cardio/strength sport) with
# an automatic fall-back to running if the account/API rejects it.
_RUNNING_SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}
_FITNESS_SPORT = {"sportTypeId": 6, "sportTypeKey": "fitness_equipment"}
_CYCLING_SPORT = {"sportTypeId": 2, "sportTypeKey": "cycling"}  # SportType.CYCLING
_SPORT_BY_WORKOUT_TYPE = {
    "hyrox_mixed": _FITNESS_SPORT,
    "cross_training": _FITNESS_SPORT,
}


# A reconcile pushes three plan weeks — ~20-30 back-to-back workout writes.
# _sync_details already paces its reads for the same reason; unpaced writes are
# the surer way to trip Garmin's per-IP rate limiting, since every athlete here
# egresses through the same WARP address. Tests set this to 0.
WRITE_PACE_SECONDS = 0.5


def _pace_writes() -> None:
    if WRITE_PACE_SECONDS:
        time.sleep(WRITE_PACE_SECONDS)


def _sport_for(workout: Workout) -> dict:
    if workout.sport == "bike":
        return _CYCLING_SPORT
    return _SPORT_BY_WORKOUT_TYPE.get(str(workout.workout_type), _RUNNING_SPORT)


# Garmin's numeric training-status codes (device DTO). 8 ("Strained") appears on
# newer firmware; unmapped codes fall through as their raw string.
_STATUS_MAP = {
    0: "No Status", 1: "Detraining", 2: "Recovery", 3: "Maintaining",
    4: "Productive", 5: "Peaking", 6: "Overreaching", 7: "Unproductive",
    8: "Strained",
}


class GarminClient:
    """High-level Garmin Connect operations for PaceForge."""

    def __init__(
        self,
        email: str,
        password: str,
        token_dir: str = DEFAULT_TOKEN_DIR,
        prompt_mfa: object | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._token_dir = token_dir
        self._prompt_mfa = prompt_mfa or (lambda: input("MFA code: "))
        self._client: Garmin | None = None
        self._mfa_state: dict | None = None
        # Per-endpoint outcome of the last get_fitness_profile() call — the
        # sync-status file surfaces this so partial fetches stop being invisible.
        self.endpoint_report: dict[str, dict] = {}

    @contextlib.contextmanager
    def _endpoint(self, name: str):
        """Best-effort fetch guard: swallow the error but record it in endpoint_report."""
        try:
            yield
            self.endpoint_report[name] = {"ok": True}
        except Exception as e:
            logger.warning("Could not fetch %s", name, exc_info=True)
            self.endpoint_report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def login(self) -> str | None:
        """Authenticate with Garmin Connect.

        Returns None on success, or "mfa_required" if an MFA code is needed
        (call complete_mfa() with the code to finish).
        """
        self._client = Garmin(
            self._email,
            self._password,
            return_on_mfa=True,
        )
        logger.info("Authenticating with Garmin Connect (may take 30-45s on first login)...")
        result = self._client.login(self._token_dir)
        # result is (needs_mfa, legacy_token) — needs_mfa is truthy when MFA required
        if result and result[0]:
            self._mfa_state = result[0] if isinstance(result[0], dict) else {}
            logger.info("MFA required — waiting for code")
            return "mfa_required"
        logger.info("Authenticated with Garmin Connect")
        return None

    def complete_mfa(self, mfa_code: str) -> None:
        """Submit the MFA code to complete authentication."""
        if self._client is None:
            raise RuntimeError("Call login() first before completing MFA.")

        # The pinned fork's public resume_login() dispatches on the same MFA
        # session attributes (widget / portal-web / cffi / mobile) this method
        # used to poke by hand, and also refetches profile + user settings.
        # An expired/lost MFA session surfaces as AttributeError inside it.
        try:
            self._client.resume_login(self._mfa_state or {}, mfa_code)
        except AttributeError as exc:
            raise RuntimeError(
                "MFA session expired or was lost. Please restart the login."
            ) from exc

        self._mfa_state = None

        # Persist tokens after successful MFA so future logins skip MFA
        if self._token_dir:
            try:
                self._client.client.dump(str(Path(self._token_dir).expanduser().resolve()))
            except Exception:
                logger.debug("Token persistence after MFA failed", exc_info=True)

        logger.info("MFA verified — authenticated with Garmin Connect")

    @classmethod
    def try_reconnect(cls, email: str, token_dir: str) -> GarminClient | None:
        """Attempt to restore a session from cached tokens (no password needed).

        Returns a connected GarminClient on success, or None if tokens are
        expired / missing.
        """
        try:
            instance = cls(email=email, password="", token_dir=token_dir)
            result = instance.login()
            if result == "mfa_required":
                logger.info("Reconnect needs MFA — treating as failed")
                return None
            logger.info("Reconnected to Garmin from cached tokens")
            return instance
        except Exception:
            logger.info("Garmin reconnect failed — tokens may be expired", exc_info=True)
            return None

    @property
    def client(self) -> Garmin:
        if self._client is None:
            raise RuntimeError("Not logged in. Call login() first.")
        return self._client

    def dump_tokens(self, token_dir: str) -> None:
        """Persist the current (possibly auto-refreshed) OAuth tokens to disk.

        Garmin's OAuth2 token is short-lived and refreshed from the OAuth1
        token during a session; writing it back keeps headless runs from
        re-loading a stale token next time.
        """
        self.client.garth.dump(str(Path(token_dir).expanduser()))

    # ── Read operations ──────────────────────────────────────────────

    def get_fitness_profile(self, lookback_days: int = 90, activity_types: list[str] | None = None) -> UserFitnessProfile:
        """Build an aggregated fitness profile from Garmin data."""
        today = date.today().isoformat()
        # Garmin populates daily metrics after sleep/wakeup — use yesterday
        # for endpoints that return empty data when today has no readings yet.
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.endpoint_report = {}

        # Basic stats
        stats = self.client.get_stats(today) or {}
        hr_data = self.client.get_heart_rates(today) or {}

        # Training status — fetch first because it also carries VO2max/load
        training_status = None
        training_load_7day = None
        load_focus = None
        vo2 = None
        fitness_age = None
        with self._endpoint("training_status"):
            ts_data = self.client.get_training_status(yesterday)
            if ts_data and isinstance(ts_data, dict):
                # VO2max lives inside mostRecentVO2Max
                mr_vo2 = ts_data.get("mostRecentVO2Max")
                if mr_vo2 and isinstance(mr_vo2, dict):
                    generic = mr_vo2.get("generic") or {}
                    vo2 = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
                    fitness_age = generic.get("fitnessAge")

                # Training status is nested under mostRecentTrainingStatus -> latestTrainingStatusData -> {deviceId}
                mr_ts = ts_data.get("mostRecentTrainingStatus") or {}
                latest_map = mr_ts.get("latestTrainingStatusData") or {}
                if latest_map:
                    # Pick primary device or first available
                    device_data = None
                    for _dev_id, dev_info in latest_map.items():
                        if isinstance(dev_info, dict):
                            if dev_info.get("primaryTrainingDevice"):
                                device_data = dev_info
                                break
                            if device_data is None:
                                device_data = dev_info
                    if device_data:
                        raw_status = device_data.get("trainingStatus")
                        if isinstance(raw_status, (int, float)):
                            training_status = _STATUS_MAP.get(int(raw_status), str(raw_status))
                        elif isinstance(raw_status, str) and raw_status:
                            training_status = raw_status
                        # Training load from acute load DTO
                        acute_dto = device_data.get("acuteTrainingLoadDTO") or {}
                        training_load_7day = (
                            acute_dto.get("dailyTrainingLoadChronic")
                            or acute_dto.get("dailyTrainingLoadAcute")
                            or device_data.get("weeklyTrainingLoad")
                        )

                # Load focus from mostRecentTrainingLoadBalance
                mr_lb = ts_data.get("mostRecentTrainingLoadBalance") or {}
                lb_map = mr_lb.get("metricsTrainingLoadBalanceDTOMap") or {}
                if lb_map:
                    lb_data = None
                    for _dev_id, dev_info in lb_map.items():
                        if isinstance(dev_info, dict):
                            if dev_info.get("primaryTrainingDevice"):
                                lb_data = dev_info
                                break
                            if lb_data is None:
                                lb_data = dev_info
                    if lb_data:
                        load_focus = lb_data.get("trainingBalanceFeedbackPhrase")
                        # Make it human-readable
                        if load_focus:
                            load_focus = load_focus.replace("_", " ").title()

                # Fallback: flat fields (older API format)
                if not training_status:
                    training_status = (
                        ts_data.get("trainingStatus")
                        or ts_data.get("currentDayTrainingStatus")
                        or ts_data.get("trainingStatusLabel")
                    )
                    if isinstance(training_status, (int, float)):
                        training_status = _STATUS_MAP.get(int(training_status), str(training_status))

        # VO2 max fallback — try dedicated endpoint if not found in training status
        if not vo2:
            with self._endpoint("vo2_max"):
                vo2_data = self.client.get_max_metrics(yesterday)
                if vo2_data and isinstance(vo2_data, list) and len(vo2_data) > 0:
                    vo2 = vo2_data[0].get("generic", {}).get("vo2MaxPreciseValue")
                    if not fitness_age:
                        fitness_age = vo2_data[0].get("generic", {}).get("fitnessAge")

        # Training readiness — the morning (post-wakeup) reading specifically:
        # get_training_readiness can return several same-day readings (e.g. a
        # post-nap recompute), and taking tr_data[0] isn't guaranteed to be the
        # morning one that Garmin's own Morning Report and our readiness math
        # both assume.
        readiness = None
        with self._endpoint("training_readiness"):
            tr_data = self.client.get_morning_training_readiness(yesterday)
            if isinstance(tr_data, dict):
                readiness = tr_data.get("score")

        # HRV
        hrv_status = None
        hrv_value = None
        with self._endpoint("hrv"):
            hrv_data = self.client.get_hrv_data(yesterday)
            if hrv_data:
                summary = hrv_data.get("hrvSummary") or {}
                hrv_status = summary.get("status")
                hrv_value = summary.get("lastNightAvg") or summary.get("weeklyAvg")

        # Lactate threshold
        lt_hr = None
        lt_speed = None
        with self._endpoint("lactate_threshold"):
            lt_data = self.client.get_lactate_threshold(latest=True)
            if lt_data and isinstance(lt_data, dict):
                shr = lt_data.get("speed_and_heart_rate") or lt_data.get("speedAndHeartRate") or {}
                if isinstance(shr, dict):
                    lt_hr = shr.get("heartRate")
                    # Garmin returns LT speed in inconsistent units — normalize to m/s
                    # at ingestion so the stored profile is correct everywhere.
                    lt_speed = _normalize_lt_speed(shr.get("speed"))

        # Endurance score
        endurance = None
        with self._endpoint("endurance_score"):
            es_data = self.client.get_endurance_score(yesterday)
            if es_data and isinstance(es_data, dict):
                endurance = (
                    es_data.get("overallScore")
                    or es_data.get("enduranceScore")
                    or es_data.get("compositeScore")
                )

        # Hill Score — uphill-running strength/endurance composite (separate
        # model from the flat-ground endurance score above).
        hill_score = None
        with self._endpoint("hill_score"):
            hs_data = self.client.get_hill_score(yesterday)
            if hs_data and isinstance(hs_data, dict):
                hill_score = (
                    hs_data.get("overallScore")
                    or hs_data.get("hillScore")
                    or hs_data.get("compositeScore")
                )

        # Overnight respiration & pulse ox — illness early-warning signals:
        # elevated overnight respiration and depressed SpO2 both move days
        # before HRV/RHR react to an oncoming infection.
        respiration_avg = None
        with self._endpoint("respiration"):
            resp_data = self.client.get_respiration_data(yesterday)
            if resp_data and isinstance(resp_data, dict):
                respiration_avg = (
                    resp_data.get("avgSleepRespirationValue")
                    or resp_data.get("avgWakingRespirationValue")
                )

        spo2_avg = None
        with self._endpoint("spo2"):
            spo2_data = self.client.get_spo2_data(yesterday)
            if spo2_data and isinstance(spo2_data, dict):
                spo2_avg = (
                    spo2_data.get("averageSpO2")
                    or spo2_data.get("avgSleepSpO2")
                    or spo2_data.get("averageSPO2")
                )

        # Running tolerance — Garmin's impact-load capacity model; stored as a
        # cross-check against the home-grown ACWR guardrail in engine/load.py.
        running_tolerance = None
        with self._endpoint("running_tolerance"):
            rt_data = self.client.get_running_tolerance(yesterday, yesterday, aggregation="daily")
            if rt_data and isinstance(rt_data, list) and isinstance(rt_data[-1], dict):
                last = rt_data[-1]
                running_tolerance = (
                    last.get("tolerance")
                    or last.get("runningTolerance")
                    or last.get("overallTolerance")
                    or last.get("weeklyRunningDistanceCapability")
                )

        # Body composition (weight)
        weight = None
        with self._endpoint("body_composition"):
            bc_data = self.client.get_body_composition(today)
            if bc_data and isinstance(bc_data, dict):
                # Weight could be in grams or kg depending on API version
                w = bc_data.get("weight")
                if w and w > 500:  # likely grams
                    weight = round(w / 1000, 1)
                elif w:
                    weight = round(w, 1)

        # Body Battery
        bb_current = None
        bb_high = None
        bb_low = None
        with self._endpoint("body_battery"):
            bb_data = self.client.get_body_battery(today)
            logger.debug("Body battery raw type=%s", type(bb_data).__name__)
            if bb_data and isinstance(bb_data, (list, dict)):
                # Handle both list and dict response formats
                if isinstance(bb_data, list) and len(bb_data) > 0:
                    # The list may contain raw timeline entries or summary dicts
                    # Look for the latest entry with a charged/level value
                    for entry in reversed(bb_data):
                        if isinstance(entry, dict):
                            v = (
                                entry.get("bodyBatteryLevel")
                                or entry.get("charged")
                                or entry.get("bodyBatteryStatus")
                            )
                            if v is not None and isinstance(v, (int, float)):
                                bb_current = int(v)
                                bb_high = entry.get("bodyBatteryHigh") or entry.get("high")
                                bb_low = entry.get("bodyBatteryLow") or entry.get("low")
                                break
                elif isinstance(bb_data, dict):
                    # Could be wrapped: {"bodyBatteryValuesArray": [...], ...}
                    arr = bb_data.get("bodyBatteryValuesArray") or bb_data.get("chartValueList") or []
                    if arr and isinstance(arr, list):
                        for entry in reversed(arr):
                            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                                bb_current = int(entry[1])
                                break
                            elif isinstance(entry, dict):
                                v = entry.get("value") or entry.get("bodyBatteryLevel")
                                if v is not None:
                                    bb_current = int(v)
                                    break
                    if bb_current is None:
                        bb_current = bb_data.get("bodyBatteryLevel") or bb_data.get("charged")
                        bb_high = bb_data.get("bodyBatteryHigh") or bb_data.get("high")
                        bb_low = bb_data.get("bodyBatteryLow") or bb_data.get("low")
            logger.debug("Body battery parsed: current=%s high=%s low=%s", bb_current, bb_high, bb_low)

        # Sleep data
        sleep_score = None
        sleep_duration = None
        sleep_deep = None
        sleep_light = None
        sleep_rem = None
        sleep_awake = None
        sleep_avg_stress = None
        spo2_lowest = None
        skin_temp_dev = None
        restless_moments = None
        bb_overnight = None
        with self._endpoint("sleep"):
            sl_data = self.client.get_sleep_data(today)
            logger.debug("Sleep data raw keys=%s", list(sl_data.keys()) if isinstance(sl_data, dict) else type(sl_data).__name__)
            if sl_data and isinstance(sl_data, dict):
                daily = sl_data.get("dailySleepDTO", sl_data)
                sleep_score = (
                    daily.get("sleepScores", {}).get("overall", {}).get("value")
                    or daily.get("sleepQualityScore")
                    or daily.get("sleepScore")
                    or sl_data.get("sleepScores", {}).get("overall", {}).get("value")
                )
                sleep_duration = daily.get("sleepTimeSeconds")
                sleep_deep = daily.get("deepSleepSeconds")
                sleep_light = daily.get("lightSleepSeconds")
                sleep_rem = daily.get("remSleepSeconds")
                sleep_awake = daily.get("awakeSleepSeconds")
                sleep_avg_stress = daily.get("avgSleepStress")
                spo2_lowest = daily.get("lowestSpO2Value")
                # Top-level (not in dailySleepDTO) — extraction map per garmin-grafana.
                skin_temp_dev = sl_data.get("avgSkinTempDeviationC")
                restless_moments = sl_data.get("restlessMomentsCount")
                bb_overnight = sl_data.get("bodyBatteryChange")
            logger.debug("Sleep parsed: score=%s duration=%s", sleep_score, sleep_duration)

        # Stress data
        stress_avg = None
        stress_high = None
        stress_low = None
        with self._endpoint("stress"):
            st_data = self.client.get_stress_data(today)
            logger.debug("Stress data raw keys=%s", list(st_data.keys()) if isinstance(st_data, dict) else type(st_data).__name__)
            if st_data and isinstance(st_data, dict):
                stress_avg = (
                    st_data.get("overallStressLevel")
                    or st_data.get("averageStressLevel")
                    or st_data.get("avgStressLevel")
                )
                stress_high = st_data.get("highStressDuration") or st_data.get("maxStressLevel")
                stress_low = st_data.get("lowStressDuration") or st_data.get("minStressLevel")
            logger.debug("Stress parsed: avg=%s", stress_avg)

        # Race predictions
        predictions: list[RacePrediction] = []
        with self._endpoint("race_predictions"):
            rp_data = self.client.get_race_predictions()
            if rp_data:
                logger.debug("Race predictions raw: %s", type(rp_data).__name__)
                if isinstance(rp_data, dict):
                    for key, label in [
                        ("5K", "5K"), ("5k", "5K"),
                        ("10K", "10K"), ("10k", "10K"),
                        ("half", "HALF_MARATHON"), ("halfMarathon", "HALF_MARATHON"),
                        ("marathon", "MARATHON"),
                    ]:
                        val = rp_data.get(key)
                        if val and isinstance(val, dict) and val.get("predictedTime"):
                            predictions.append(
                                RacePrediction(
                                    distance=label,
                                    predicted_seconds=val["predictedTime"],
                                )
                            )
                elif isinstance(rp_data, list):
                    for item in rp_data:
                        if isinstance(item, dict):
                            dist = item.get("raceDistance") or item.get("distance") or ""
                            secs = item.get("predictedTime") or item.get("time") or 0
                            if dist and secs:
                                _DIST_NORM = {
                                    "5K": "5K", "5k": "5K",
                                    "10K": "10K", "10k": "10K",
                                    "halfMarathon": "HALF_MARATHON", "half": "HALF_MARATHON",
                                    "HALF_MARATHON": "HALF_MARATHON",
                                    "marathon": "MARATHON", "MARATHON": "MARATHON",
                                }
                                label = _DIST_NORM.get(dist, dist)
                                predictions.append(RacePrediction(distance=label, predicted_seconds=secs))

        # Personal records
        personal_records: list[PersonalRecord] = []
        with self._endpoint("personal_records"):
            pr_data = self.client.get_personal_record()
            if pr_data and isinstance(pr_data, (list, dict)):
                items = pr_data if isinstance(pr_data, list) else pr_data.get("personalRecords", [])
                _DIST_MAP = {
                    5000: "5K", 10000: "10K", 21097: "HALF_MARATHON",
                    21097.5: "HALF_MARATHON", 42195: "MARATHON",
                }
                for pr in items:
                    if not isinstance(pr, dict):
                        continue
                    pr_type = pr.get("personalRecordType", "")
                    if pr_type not in ("FASTEST_DISTANCE",):
                        continue
                    dist_m = pr.get("value")  # distance in meters for distance PRs
                    # Time in seconds — try multiple possible keys
                    time_s = pr.get("elapsedTime") or pr.get("duration") or pr.get("timeInSeconds")
                    pr_date = pr.get("prStartTimeLocal", "")
                    # Try to get distance label
                    label = _DIST_MAP.get(dist_m)
                    if label and time_s and float(time_s) > 0:
                        personal_records.append(
                            PersonalRecord(distance=label, time_seconds=float(time_s), record_date=str(pr_date) if pr_date else None)
                        )

        # Recent activities (multiple types supported)
        activities: list[RecentActivity] = []
        # None => Garmin returns every activity type (runs, cardio, strength, …).
        _act_types = activity_types or [None]
        with self._endpoint("activities"):
            start = (date.today() - timedelta(days=lookback_days)).isoformat()
            raw: list = []
            for _atype in _act_types:
                try:
                    _type_raw = self.client.get_activities_by_date(start, today, _atype)
                    raw.extend(_type_raw or [])
                except Exception:
                    logger.warning("Could not fetch %s activities", _atype, exc_info=True)
            # Deduplicate by activityId
            _seen_ids: set[int] = set()
            _deduped: list[dict] = []
            for _a in raw:
                _aid = _a.get("activityId", 0)
                if _aid not in _seen_ids:
                    _seen_ids.add(_aid)
                    _deduped.append(_a)
            raw = _deduped
            for act in raw:
                activities.append(
                    RecentActivity(
                        activity_id=act.get("activityId", 0),
                        name=act.get("activityName", ""),
                        activity_type=act.get("activityType", {}).get("typeKey", "running"),
                        start_time=act.get("startTimeLocal", ""),
                        distance_meters=act.get("distance", 0),
                        duration_seconds=act.get("duration", 0),
                        avg_hr=act.get("averageHR"),
                        max_hr=act.get("maxHR"),
                        avg_pace_sec_per_km=_meters_per_sec_to_sec_per_km(
                            act.get("averageSpeed")
                        ),
                        calories=act.get("calories"),
                        training_effect_aerobic=act.get("aerobicTrainingEffect"),
                        training_effect_anaerobic=act.get("anaerobicTrainingEffect"),
                        vo2_max_value=act.get("vO2MaxValue"),
                        avg_running_cadence=act.get("averageRunningCadenceInStepsPerMinute"),
                        # Running dynamics
                        avg_stride_length=act.get("avgStrideLength"),
                        avg_ground_contact_time=act.get("avgGroundContactTime"),
                        avg_vertical_oscillation=act.get("avgVerticalOscillation"),
                        avg_vertical_ratio=act.get("avgVerticalRatio"),
                        avg_power=act.get("avgPower"),
                        elevation_gain=act.get("elevationGain"),
                        avg_respiration_rate=act.get("avgRespirationRate"),
                    )
                )

        # Weekly mileage estimate
        weekly_km = None
        if activities:
            total_m = sum(a.distance_meters for a in activities)
            weekly_km = round((total_m / 1000) / max(lookback_days / 7, 1), 1)

        # HR zones
        zones: list[HRZone] = []
        with self._endpoint("hr_zones"):
            zone_data = hr_data.get("heartRateZones")
            if zone_data:
                for i, z in enumerate(zone_data, 1):
                    zones.append(
                        HRZone(
                            zone=i,
                            low_bpm=z.get("startBPM", 0),
                            high_bpm=z.get("endBPM", 0),
                        )
                    )

        return UserFitnessProfile(
            garmin_display_name=stats.get("displayName"),
            vo2_max=vo2,
            resting_hr=hr_data.get("restingHeartRate"),
            # Ignore sensor-glitch spikes (e.g. a 230 bpm cadence-lock) when taking
            # the observed max — they corrupt HR-zone and training-load maths downstream.
            max_hr=max(
                (a.max_hr for a in activities if a.max_hr and a.max_hr <= 210),
                default=None,
            ) or hr_data.get("maxHeartRate") or stats.get("maxAvgHeartRate"),
            hr_zones=zones,
            training_readiness=readiness,
            training_status=training_status,
            hrv_status=hrv_status,
            hrv_last_night=hrv_value,
            weekly_mileage_km=weekly_km,
            lactate_threshold_hr=lt_hr,
            lactate_threshold_speed=lt_speed,
            endurance_score=endurance,
            weight_kg=weight,
            race_predictions=predictions,
            personal_records=personal_records,
            recent_activities=activities,
            # New fields
            body_battery_current=bb_current,
            body_battery_high=bb_high,
            body_battery_low=bb_low,
            sleep_score=sleep_score,
            sleep_duration_seconds=sleep_duration,
            sleep_deep_seconds=sleep_deep,
            sleep_light_seconds=sleep_light,
            sleep_rem_seconds=sleep_rem,
            sleep_awake_seconds=sleep_awake,
            stress_avg=stress_avg,
            stress_high=stress_high,
            stress_low=stress_low,
            training_load_7day=training_load_7day,
            load_focus=load_focus,
            fitness_age=fitness_age,
            hill_score=hill_score,
            respiration_avg_sleep=respiration_avg,
            spo2_avg=spo2_avg,
            spo2_lowest=spo2_lowest,
            skin_temp_deviation_c=skin_temp_dev,
            sleep_restless_moments=restless_moments,
            body_battery_overnight_change=bb_overnight,
            sleep_avg_stress=sleep_avg_stress,
            running_tolerance=running_tolerance,
        )

    # ── Activity detail ──────────────────────────────────────────────

    def get_activity_detail(self, activity_id: int) -> dict:
        """Fetch detailed data for a specific activity (splits, HR zones, summary)."""
        result: dict = {"activity_id": activity_id}

        try:
            result["splits"] = self.client.get_activity_splits(activity_id)
        except Exception:
            logger.warning("Could not fetch splits for %s", activity_id, exc_info=True)
            result["splits"] = None

        try:
            result["hr_zones"] = self.client.get_activity_hr_in_timezones(activity_id)
        except Exception:
            logger.warning("Could not fetch HR zones for %s", activity_id, exc_info=True)
            result["hr_zones"] = None

        try:
            result["summary"] = self.client.get_activity(activity_id)
        except Exception:
            logger.warning("Could not fetch summary for %s", activity_id, exc_info=True)
            result["summary"] = None

        # Per-km split summaries (more granular than lap splits)
        try:
            result["split_summaries"] = self.client.get_activity_split_summaries(activity_id)
        except Exception:
            logger.debug("split_summaries unavailable for %s", activity_id)
            result["split_summaries"] = None

        # Weather conditions during the activity
        try:
            result["weather"] = self.client.get_activity_weather(activity_id)
        except Exception:
            logger.debug("weather unavailable for %s", activity_id)
            result["weather"] = None

        # Downsampled time-series (HR + speed over time) for the detail charts.
        try:
            result["metrics"] = self.client.get_activity_details(activity_id, maxchart=200)
        except Exception:
            logger.debug("time-series metrics unavailable for %s", activity_id)
            result["metrics"] = None

        # Per-set exercise data for gym work (reps/weight/exercise name — the API
        # copy carries user-corrected names, unlike the FIT file). Strength only:
        # other sports have no sets and the extra call would be wasted.
        summary = result.get("summary") or {}
        type_key = str(((summary.get("activityTypeDTO") or summary.get("activityType") or {})
                        ).get("typeKey", ""))
        if "strength" in type_key.lower():
            try:
                result["exercise_sets"] = self.client.get_activity_exercise_sets(activity_id)
            except Exception:
                logger.debug("exercise sets unavailable for %s", activity_id)
                result["exercise_sets"] = None

        return result

    def get_all_workouts(self) -> list[dict]:
        """Fetch all workouts from the Garmin workout library, paginating if needed."""
        all_workouts: list[dict] = []
        start = 0
        batch_size = 200
        while True:
            batch = self.client.get_workouts(start=start, limit=batch_size)
            if not batch:
                break
            all_workouts.extend(batch)
            if len(batch) < batch_size:
                break
            start += batch_size
        return all_workouts

    def get_scheduled_workouts(self, days_ahead: int = 30) -> list[dict]:
        """Fetch scheduled workouts from Garmin calendar for the next N days."""
        scheduled = []

        # Method 1: calendar-service month view — the authoritative source for
        # scheduled workouts on the Garmin calendar (month is 0-indexed).
        try:
            end = date.today() + timedelta(days=days_ahead)
            cursor = date.today().replace(day=1)
            seen_months: set[tuple[int, int]] = set()
            while cursor <= end:
                key = (cursor.year, cursor.month)
                if key not in seen_months:
                    seen_months.add(key)
                    data = self.client.connectapi(
                        f"/calendar-service/year/{cursor.year}/month/{cursor.month - 1}"
                    )
                    for item in (data or {}).get("calendarItems", []):
                        if item.get("itemType") != "workout":
                            continue
                        cal_date = item.get("date")
                        wid = item.get("workoutId")
                        if not cal_date or not wid:
                            continue
                        scheduled.append({
                            "workout_id": wid,
                            "name": item.get("title", "Workout"),
                            "description": "",
                            "scheduled_date": str(cal_date)[:10],
                            "sport_type": "",
                            "estimated_duration_seconds": item.get("duration"),
                            "estimated_distance_meters": item.get("distance"),
                        })
                cursor = (cursor + timedelta(days=32)).replace(day=1)
            if scheduled:
                return scheduled
        except Exception:
            logger.debug("calendar-service failed, trying workout library", exc_info=True)

        # Method 2: Fall back to workout library (all workouts with a calendarDate)
        try:
            workouts = self.get_all_workouts()
            for w in workouts:
                cal_date = w.get("calendarDate")
                if not cal_date:
                    continue
                scheduled.append({
                    "workout_id": w.get("workoutId"),
                    "name": w.get("workoutName", "Workout"),
                    "description": w.get("description", ""),
                    "scheduled_date": str(cal_date)[:10],
                    "sport_type": (w.get("sportType") or {}).get("sportTypeKey", ""),
                    "estimated_duration_seconds": w.get("estimatedDurationInSecs"),
                    "estimated_distance_meters": w.get("estimatedDistanceInMeters"),
                })
        except Exception:
            logger.warning("Could not fetch Garmin workouts", exc_info=True)

        # Method 3: Try daily events for upcoming days if nothing found.
        # The fork has no range endpoint for all-day events (one API call per day),
        # so cap this last-resort sweep — callers pass days_ahead up to 400.
        if not scheduled:
            for d in range(min(days_ahead, 60)):
                try:
                    day = (date.today() + timedelta(days=d)).isoformat()
                    events = self.client.get_all_day_events(day)
                    if isinstance(events, list):
                        for ev in events:
                            ev_type = ev.get("eventType", {})
                            if isinstance(ev_type, dict) and ev_type.get("typeKey") == "workout":
                                scheduled.append({
                                    "workout_id": ev.get("workoutId"),
                                    "name": ev.get("eventName", "Scheduled Workout"),
                                    "description": ev.get("description", ""),
                                    "scheduled_date": day,
                                    "sport_type": "",
                                    "estimated_duration_seconds": ev.get("durationInSecs"),
                                    "estimated_distance_meters": None,
                                })
                except Exception:
                    logger.debug("Could not fetch daily events for %s", day)
                    continue

        return scheduled

    # ── Write operations ─────────────────────────────────────────────

    def delete_workout(self, workout_id: int | str) -> bool:
        """Delete a workout from Garmin Connect by ID.

        Raises on failure — callers must catch it, keep their
        ``garmin_workout_id`` and record/retry instead of leaving a stale
        copy on the watch.
        """
        self.client.delete_workout(int(workout_id))
        logger.info("Deleted Garmin workout %s", workout_id)
        _pace_writes()
        return True

    def push_workout(self, workout: Workout, schedule_date: date | None = None,
                     plan_paces: dict | None = None, pace_bands: dict | None = None) -> dict:
        """Upload a structured workout to Garmin Connect and optionally schedule it.

        HYROX/station workouts go up as fitness_equipment (Garmin's cardio/strength
        sport); if Garmin rejects that, we retry as a running workout with the
        stations spelled out in the step descriptions — works on any watch.
        """
        sport = _sport_for(workout)
        try:
            result = self._upload(workout, sport, plan_paces, pace_bands)
        except Exception:
            if sport["sportTypeKey"] == "running":
                raise
            logger.warning("%s upload as %s rejected — retrying as running",
                           workout.name, sport["sportTypeKey"], exc_info=True)
            sport = _RUNNING_SPORT
            result = self._upload(workout, sport, plan_paces, pace_bands)
        workout_id = result.get("workoutId")
        result["sport_used"] = sport["sportTypeKey"]
        logger.info("Uploaded workout %s (id=%s, sport=%s)",
                    workout.name, workout_id, sport["sportTypeKey"])

        if schedule_date and workout_id:
            self.client.schedule_workout(workout_id, schedule_date.isoformat())
            logger.info("Scheduled workout %s on %s", workout_id, schedule_date)

        _pace_writes()
        return result

    def _upload(self, workout: Workout, sport: dict, plan_paces: dict | None,
                pace_bands: dict | None = None) -> dict:
        steps = workout.steps or _fallback_steps(workout, plan_paces, pace_bands)
        garmin_steps = _renumber_steps(
            [_to_garmin_step(step, order=i + 1, pace_bands=pace_bands,
                             cadence=workout.cadence_target, briefing=workout.briefing)
             for i, step in enumerate(steps)])
        garmin_workout = RunningWorkout(
            workoutName=workout.name,
            description=_build_garmin_description(workout, plan_paces),
            estimatedDurationInSecs=int(workout.estimated_duration_seconds or 3600),
            sportType=sport,
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType=sport,
                    workoutSteps=garmin_steps,
                )
            ],
        )
        if workout.estimated_distance_meters:
            # Without this the Garmin workout card shows 0 km planned.
            garmin_workout.estimatedDistanceInMeters = float(  # type: ignore[attr-defined]
                workout.estimated_distance_meters)
        return self.client.upload_running_workout(garmin_workout)

    # ── Weight & body composition ────────────────────────────────────

    def get_weight_history(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch weigh-in entries from Garmin for a date range.

        Returns list of dicts with: date, weight_kg, bmi, body_fat_pct,
        muscle_mass_kg, source='garmin'.
        """
        try:
            raw = self.client.get_weigh_ins(
                start_date.isoformat(), end_date.isoformat()
            )
        except Exception:
            logger.warning("Could not fetch weigh-ins", exc_info=True)
            return []

        entries = []
        # Response structure: {"dailyWeightSummaries": [...]}
        summaries = []
        if isinstance(raw, dict):
            summaries = raw.get("dailyWeightSummaries") or raw.get("dateWeightList") or []
        elif isinstance(raw, list):
            summaries = raw

        for item in summaries:
            try:
                cal_date = item.get("summaryDate") or item.get("calendarDate") or item.get("date")
                if not cal_date:
                    continue
                # Weight can be at top level or nested
                weight_g = item.get("weight") or item.get("maxWeight") or 0
                if weight_g <= 0:
                    continue
                weight_kg = round(weight_g / 1000, 1) if weight_g > 500 else round(weight_g, 1)
                entries.append({
                    "date": cal_date,
                    "weight_kg": weight_kg,
                    "bmi": item.get("bmi"),
                    "body_fat_pct": item.get("bodyFat"),
                    "muscle_mass_kg": round(item.get("muscleMass", 0) / 1000, 1) if item.get("muscleMass") and item["muscleMass"] > 500 else item.get("muscleMass"),
                    "source": "garmin",
                })
            except Exception:
                logger.debug("Skipping weigh-in item: %s", item, exc_info=True)
        return entries

    def get_body_composition(self, target_date: date) -> dict:
        """Fetch body composition data for a specific date."""
        try:
            raw = self.client.get_body_composition(
                target_date.isoformat(), target_date.isoformat()
            )
            if isinstance(raw, dict):
                return raw
        except Exception:
            logger.warning("Could not fetch body composition for %s", target_date, exc_info=True)
        return {}

    def push_plan_week(self, workouts: list[Workout], plan_paces: dict | None = None,
                       pace_bands: dict | None = None) -> dict:
        """Push a list of workouts (typically one week) to Garmin Connect.

        Dedup: deletes each workout's previously-pushed Garmin copy by stored id
        (``garmin_workout_id``), with a name+date-range sweep as the fallback for
        workouts pushed before ids were recorded. Uploads are isolated per
        workout — one failure doesn't abort the rest of the week. Sets
        ``garmin_workout_id`` on each pushed workout (caller persists the plan).
        """
        active = [w for w in workouts if w.workout_type.value != "rest"]
        if not active:
            return {"pushed": [], "failed": []}

        pushed: list[dict] = []
        failed: list[dict] = []
        # Delete-by-id for previously pushed copies. A failed delete keeps the
        # id, is recorded and skips that workout's upload — the alternative is
        # a duplicate on the watch with the stale copy still there.
        delete_failed: set[int] = set()
        for w in active:
            if w.garmin_workout_id:
                try:
                    self.delete_workout(w.garmin_workout_id)
                except Exception as e:
                    logger.warning("Delete failed for %s (Garmin id %s) — skipping its upload",
                                   w.name, w.garmin_workout_id, exc_info=True)
                    delete_failed.add(id(w))
                    failed.append({"name": w.name, "error": f"{type(e).__name__}: {e}"})
        # …then the legacy name+date sweep for anything pushed before ids existed.
        dates = [w.scheduled_date for w in active if w.scheduled_date]
        untracked = {w.name for w in active if not w.garmin_workout_id}
        if dates and untracked:
            min_date, max_date = min(dates), max(dates)
            try:
                for ex in self.get_all_workouts():
                    ex_date = str(ex.get("calendarDate") or "")[:10]
                    ex_id = ex.get("workoutId")
                    if (ex_id and ex_date and ex.get("workoutName", "") in untracked
                            and str(min_date) <= ex_date <= str(max_date)):
                        self.delete_workout(ex_id)
            except Exception:
                logger.warning("Could not clean up existing workouts before push", exc_info=True)

        for w in active:
            if id(w) in delete_failed:
                continue
            try:
                r = self.push_workout(w, schedule_date=w.scheduled_date,
                                      plan_paces=plan_paces, pace_bands=pace_bands)
                if r.get("workoutId"):
                    w.garmin_workout_id = int(r["workoutId"])
                pushed.append({"name": w.name, "workout_id": r.get("workoutId"),
                               "sport": r.get("sport_used")})
            except Exception as e:
                logger.warning("Push failed for %s", w.name, exc_info=True)
                failed.append({"name": w.name, "error": f"{type(e).__name__}: {e}"})
        return {"pushed": pushed, "failed": failed}


def _truncate_at_word(text: str, limit: int) -> str:
    """Cut at a word boundary with an ellipsis — a mid-word cut reads as a typo."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    head = cut.rsplit(None, 1)
    if not text[limit - 1].isspace() and len(head) == 2:
        cut = head[0]
    return cut.rstrip() + "…"


def _build_garmin_description(workout: Workout, plan_paces: dict | None = None) -> str:
    """Build the ≤500-char description for the Garmin watch preview screen.

    Leads with the briefing (purpose → feel → cue), then Claude's coaching
    note. Deliberately NO pace/step recap lines — the watch already renders
    every step and target, and those lines used to truncate the coaching text.
    """
    briefing = workout.briefing or {}
    parts = [p for p in (
        briefing.get("purpose"),
        f"Feel: {briefing['feel']}" if briefing.get("feel") else None,
        f"Cue: {briefing['cue']}" if briefing.get("cue") else None,
        f"Cadence: ~{workout.cadence_target} spm on the work reps"
        if workout.cadence_target else None,
        workout.notes,
    ) if p]
    result = "\n".join(parts) or workout.description
    return _truncate_at_word(result, 500)


def _meters_per_sec_to_sec_per_km(speed: float | None) -> float | None:
    if not speed or speed <= 0:
        return None
    return round(1000.0 / speed, 1)


# Step-less workout types whose fallback step is honestly run at easy pace.
_EASY_FALLBACK_TYPES = {
    "easy_run", "long_run", "recovery_run", "easy_with_strides",
    "long_run_progressive", "long_run_with_race_pace",
}


def _fallback_steps(workout: Workout, plan_paces: dict | None,
                    pace_bands: dict | None = None) -> list[WorkoutStep]:
    """A step-less workout still needs one structured step to load + track on Garmin.

    Non-running sessions (gym classes, HYROX stations, bike) get a single timed
    step with NO pace target — the old easy-pace cage had the watch beeping
    "speed up" through classes. Race-day sessions get the plan's race band (or
    run open), easy/long types the easy band, anything else a modest window.
    """
    name = workout.name or "Run"
    if workout.sport != "run" or str(workout.workout_type) in _SPORT_BY_WORKOUT_TYPE:
        return [WorkoutStep(
            step_type=WorkoutStepType.ACTIVE,
            description=name,
            duration_seconds=workout.estimated_duration_seconds or 3600,
            target_type=IntensityTarget.OPEN,
        )]
    bands = pace_bands or {}
    easy = (plan_paces or {}).get("easy_pace")
    modest = [easy - 5, easy + 5] if easy else None  # fast → slow, NOT inverted
    wt = str(workout.workout_type)
    if wt == "race_pace" or "RACE DAY" in name.upper():
        # All-out day: the race band when the plan has one, otherwise open —
        # never cage a race at easy pace.
        band = bands.get("race")
    elif wt in _EASY_FALLBACK_TYPES:
        band = bands.get("easy") or modest
    else:
        band = modest
    dist = workout.estimated_distance_meters
    dur = None if dist else (workout.estimated_duration_seconds or 1800)
    lo, hi = band if band else (None, None)
    return [WorkoutStep(
        step_type=WorkoutStepType.ACTIVE,
        description=name,
        distance_meters=dist,
        duration_seconds=dur,
        target_type=IntensityTarget.PACE if lo else IntensityTarget.OPEN,
        target_low=lo,
        target_high=hi,
    )]


def _renumber_steps(steps: list, _state: dict | None = None) -> list:
    """Renumber the step tree the way Garmin's own payloads do.

    Garmin numbers every node — repeat groups AND their children — depth-first
    sequentially across the whole workout, and tags each repeat group's
    children with a childStepId (group 1..k). Locally-restarting stepOrders
    render out of order on the watch.
    """
    state = _state if _state is not None else {"order": 0, "groups": 0}
    for s in steps:
        state["order"] += 1
        s.stepOrder = state["order"]
        if isinstance(s, RepeatGroup):
            state["groups"] += 1
            gid = state["groups"]
            for child in s.workoutSteps:
                child.childStepId = gid
            _renumber_steps(s.workoutSteps, state)
    return steps


def _to_garmin_step(step, order: int = 1, pace_bands: dict | None = None,  # noqa: ANN001
                    cadence: int | None = None, briefing: dict | None = None):
    """Convert a PaceForge WorkoutStep to a garminconnect workout step dict.

    Handles pace targets (sec/km → m/s pace zone), custom heart-rate ranges,
    power targets (watts → power.zone), and distance-based end conditions so
    the Garmin watch guides each segment. Effort-based (open-target) work
    steps get a cadence target when the workout defines one — Garmin allows a
    single target per step, so cadence never displaces a pace target.
    """
    # ── Repeat groups must be checked first ──────────────────────────
    if step.repeat_count and step.steps:
        sub_steps = [_to_garmin_step(s, i + 1, pace_bands=pace_bands, cadence=cadence,
                                     briefing=briefing)
                     for i, s in enumerate(step.steps)]
        group = create_repeat_group(step.repeat_count, sub_steps, order)
        if step.description:
            # RepeatGroup is extra="allow" — carry "6 x strides" to the watch.
            group.description = step.description[:200]  # type: ignore[attr-defined]
        return group

    has_bounds = (
        step.target_low is not None
        and step.target_high is not None
        and step.target_low > 0
        and step.target_high > 0
    )
    # Recoveries/rests are walked or jogged by feel — a pace band there makes
    # the watch alert "speed up" during every rest. They go up untargeted.
    if step.step_type in (WorkoutStepType.RECOVERY, WorkoutStepType.REST):
        has_bounds = False

    # ── Build target if available ────────────────────────────────────
    target = None
    target_val_one = None
    target_val_two = None
    if has_bounds and step.target_type == IntensityTarget.POWER:
        # Custom watt range — Garmin's power.zone target (TargetType.POWER = 2).
        target = {
            "workoutTargetTypeId": TargetType.POWER,
            "workoutTargetTypeKey": "power.zone",
            "displayOrder": 2,
        }
        target_val_one = min(step.target_low, step.target_high)
        target_val_two = max(step.target_low, step.target_high)
    elif has_bounds and step.target_type == IntensityTarget.HEART_RATE:
        # Custom bpm range (NOT a Garmin zone number) — without this, HR steps
        # silently became no.target.
        target = {
            "workoutTargetTypeId": TargetType.HEART_RATE,
            "workoutTargetTypeKey": "heart.rate.zone",
            "displayOrder": 4,
        }
        target_val_one = min(step.target_low, step.target_high)
        target_val_two = max(step.target_low, step.target_high)
    elif has_bounds:
        # A single-pace step (target_low == target_high) serializes to a
        # zero-width target that Garmin treats as no-op — this silently killed
        # pacing on every easy/warmup/cooldown step. Widen it to the plan's
        # real zone band when we know it, else a ±3 s/km fallback.
        pace_low, pace_high = step.target_low, step.target_high
        if pace_low == pace_high:
            band = (pace_bands or {}).get(step.pace_key) if step.pace_key else None
            if band and len(band) == 2 and band[0] > 0 and band[1] > 0 and band[0] != band[1]:
                pace_low, pace_high = band[0], band[1]
            else:
                pace_low, pace_high = pace_low + 3.0, pace_high - 3.0
        # Convert sec/km → m/s. Faster pace (smaller sec/km) = higher m/s.
        speed_a = round(1000.0 / pace_low, 4)
        speed_b = round(1000.0 / pace_high, 4)
        # Garmin's running pace target is pace.zone = id 6, which the watch
        # shows as a min/km range. The pinned fork mislabels id 6 as OPEN and
        # has no pace.zone constant, so emit it literally. speed.zone (5)
        # renders as km/h and does NOT pace a runner.
        target = {
            "workoutTargetTypeId": 6,
            "workoutTargetTypeKey": "pace.zone",
            "displayOrder": 6,
        }
        # Garmin expects targetValueOne <= targetValueTwo
        target_val_one = min(speed_a, speed_b)
        target_val_two = max(speed_a, speed_b)
    elif cadence and step.step_type in (WorkoutStepType.INTERVAL, WorkoutStepType.ACTIVE):
        # Effort-based work step (e.g. hill reps run on feel): give the watch a
        # cadence window so it still coaches turnover on the rep.
        target = {
            "workoutTargetTypeId": TargetType.CADENCE,
            "workoutTargetTypeKey": "cadence",
            "displayOrder": 3,
        }
        target_val_one = float(cadence - 5)
        target_val_two = float(cadence + 5)

    # ── Build end condition (distance or time) ───────────────────────
    if step.distance_meters and step.distance_meters > 0:
        end_condition = {
            "conditionTypeId": ConditionType.DISTANCE,
            "conditionTypeKey": "distance",
            "displayOrder": 1,
            "displayable": True,
        }
        end_value = step.distance_meters
    else:
        end_condition = {
            "conditionTypeId": ConditionType.TIME,
            "conditionTypeKey": "time",
            "displayOrder": 2,
            "displayable": True,
        }
        end_value = step.duration_seconds or 600.0

    # ── Map step type ────────────────────────────────────────────────
    step_type_map = {
        WorkoutStepType.WARMUP: (StepType.WARMUP, "warmup", 1),
        WorkoutStepType.COOLDOWN: (StepType.COOLDOWN, "cooldown", 2),
        WorkoutStepType.RECOVERY: (StepType.RECOVERY, "recovery", 4),
        WorkoutStepType.INTERVAL: (StepType.INTERVAL, "interval", 3),
        WorkoutStepType.ACTIVE: (StepType.INTERVAL, "interval", 3),
        WorkoutStepType.REST: (StepType.REST, "rest", 5),
    }
    type_id, type_key, type_order = step_type_map.get(
        step.step_type, (StepType.INTERVAL, "interval", 3)
    )

    garmin_step = ExecutableStep(
        stepOrder=order,
        stepType={
            "stepTypeId": type_id,
            "stepTypeKey": type_key,
            "displayOrder": type_order,
        },
        endCondition=end_condition,
        endConditionValue=end_value,
        targetType=target or {
            "workoutTargetTypeId": TargetType.NO_TARGET,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        },
    )

    # Add target values (ExecutableStep has extra="allow")
    if target_val_one is not None:
        garmin_step.targetValueOne = target_val_one  # type: ignore[attr-defined]
        garmin_step.targetValueTwo = target_val_two  # type: ignore[attr-defined]

    # Per-step notes — Garmin renders these on the watch during the step. Work
    # steps carry the briefing's feel/cue (coaching the athlete can't get
    # mid-rep) instead of restating the target the watch already shows; rests
    # keep their own informative text ("45s walking rest").
    note = step.description
    if briefing and step.step_type in (WorkoutStepType.INTERVAL, WorkoutStepType.ACTIVE):
        note = briefing.get("feel") or briefing.get("cue") or note
    if note:
        garmin_step.description = note[:200]  # type: ignore[attr-defined]

    return garmin_step
