"""Dynamic workout factory — generates varied, structured workouts by type and purpose."""

from __future__ import annotations

from paceforge.engine.vdot import ZONE_KEYS, TrainingPaces
from paceforge.models.plan import (
    IntensityTarget,
    TrainingPurpose,
    Workout,
    WorkoutStep,
    WorkoutStepType,
    WorkoutType,
)


class WorkoutFactory:
    """Generates varied workouts using VDOT-derived paces."""

    def __init__(
        self, paces: TrainingPaces | None, goal_pace_sec_km: float | None = None
    ) -> None:
        self.paces = paces
        self.goal_pace_sec_km = goal_pace_sec_km

    # ── Helper builders ──────────────────────────────────────────────

    def _pace_step(
        self,
        step_type: WorkoutStepType,
        description: str,
        *,
        duration_seconds: float | None = None,
        distance_meters: float | None = None,
        pace_low: float | None = None,
        pace_high: float | None = None,
        pace_key: str | None = None,
    ) -> WorkoutStep:
        target_type = IntensityTarget.PACE if pace_low is not None else IntensityTarget.OPEN
        return WorkoutStep(
            step_type=step_type,
            description=description,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            target_type=target_type,
            target_low=pace_low,
            target_high=pace_high,
            pace_key=pace_key if pace_low is not None else None,
        )

    def _warmup(self, minutes: float = 10) -> WorkoutStep:
        p = self.paces
        return self._pace_step(
            WorkoutStepType.WARMUP,
            f"{minutes:.0f} min warmup",
            duration_seconds=minutes * 60,
            pace_low=p.easy_low if p else None,
            pace_high=p.easy_high if p else None,
            pace_key="easy",
        )

    def _cooldown(self, minutes: float = 10) -> WorkoutStep:
        p = self.paces
        return self._pace_step(
            WorkoutStepType.COOLDOWN,
            f"{minutes:.0f} min cooldown",
            duration_seconds=minutes * 60,
            pace_low=p.easy_low if p else None,
            pace_high=p.easy_high if p else None,
            pace_key="easy",
        )

    def _easy_step(
        self,
        *,
        distance_meters: float | None = None,
        duration_seconds: float | None = None,
    ) -> WorkoutStep:
        p = self.paces
        desc = "Easy"
        if distance_meters:
            desc = f"{distance_meters / 1000:.1f} km easy"
        elif duration_seconds:
            desc = f"{duration_seconds / 60:.0f} min easy"
        return self._pace_step(
            WorkoutStepType.ACTIVE,
            desc,
            distance_meters=distance_meters,
            duration_seconds=duration_seconds,
            pace_low=p.easy_low if p else None,
            pace_high=p.easy_high if p else None,
            pace_key="easy",
        )

    def _recovery_step(self, duration_seconds: float) -> WorkoutStep:
        p = self.paces
        return self._pace_step(
            WorkoutStepType.RECOVERY,
            f"{duration_seconds / 60:.1f} min recovery jog",
            duration_seconds=duration_seconds,
            pace_low=p.easy_low if p else None,
            pace_high=p.easy_high if p else None,
            pace_key="easy",
        )

    def _resolve_pace(self, pace_key: str) -> tuple[float | None, float | None]:
        p = self.paces
        if pace_key == "race":
            # Goal race pace from target time; marathon band when no goal set.
            if self.goal_pace_sec_km:
                return (self.goal_pace_sec_km * 0.985, self.goal_pace_sec_km * 1.03)
            pace_key = "marathon"
        if not p or pace_key not in ZONE_KEYS:
            return None, None
        return p.band(pace_key)

    # ── Workout generators ───────────────────────────────────────────

    def easy_run(self, distance_km: float) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        dur = distance_km * p.easy_low if p else None
        return Workout(
            workout_type=WorkoutType.EASY_RUN,
            name=f"{distance_km:.0f}km Easy Run",
            description="Relaxed aerobic run at conversational pace. Builds base fitness.",
            purpose=TrainingPurpose.AEROBIC_BASE,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=[self._easy_step(distance_meters=dist_m)],
        )

    def easy_with_strides(self, distance_km: float, num_strides: int = 6) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        easy_dist = dist_m - num_strides * 100  # strides ~100m each
        dur = distance_km * p.easy_low if p else None
        rep_low, rep_high = self._resolve_pace("repetition")
        steps = [
            self._easy_step(distance_meters=easy_dist),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{num_strides} x strides",
                repeat_count=num_strides,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        "Stride — fast & relaxed",
                        distance_meters=100,
                        pace_low=rep_low,
                        pace_high=rep_high,
                        pace_key="repetition",
                    ),
                    self._recovery_step(45),
                ],
            ),
        ]
        return Workout(
            workout_type=WorkoutType.EASY_WITH_STRIDES,
            name=f"{distance_km:.0f}km Easy + {num_strides} Strides",
            description=(
                "Easy run finishing with short strides to develop"
                " running economy and neuromuscular coordination."
            ),
            purpose=TrainingPurpose.RUNNING_ECONOMY,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def recovery_run(self, distance_km: float) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        dur = distance_km * p.easy_high if p else None  # slower end of easy
        return Workout(
            workout_type=WorkoutType.RECOVERY,
            name=f"{distance_km:.0f}km Recovery Run",
            description=(
                "Very easy effort to promote blood flow and"
                " recovery. Keep the pace comfortable."
            ),
            purpose=TrainingPurpose.RECOVERY,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=[self._easy_step(distance_meters=dist_m)],
        )

    def long_run(self, distance_km: float) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        dur = distance_km * p.easy_low if p else None
        return Workout(
            workout_type=WorkoutType.LONG_RUN,
            name=f"{distance_km:.0f}km Long Run",
            description="Steady long run building endurance and mental toughness at easy pace.",
            purpose=TrainingPurpose.ENDURANCE,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=[self._easy_step(distance_meters=dist_m)],
        )

    def long_run_progressive(self, distance_km: float) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        easy_km = distance_km * 0.6
        mp_km = distance_km * 0.3
        threshold_km = distance_km * 0.1
        dur = None
        if p:
            dur = easy_km * p.easy_low + mp_km * p.marathon + threshold_km * p.threshold
        mp_lo, mp_hi = self._resolve_pace("marathon")
        t_lo, t_hi = self._resolve_pace("threshold")
        steps = [
            self._easy_step(distance_meters=easy_km * 1000),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{mp_km:.1f} km at marathon pace",
                distance_meters=mp_km * 1000,
                pace_low=mp_lo,
                pace_high=mp_hi,
                pace_key="marathon",
            ),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{threshold_km:.1f} km at threshold pace",
                distance_meters=threshold_km * 1000,
                pace_low=t_lo,
                pace_high=t_hi,
                pace_key="threshold",
            ),
        ]
        return Workout(
            workout_type=WorkoutType.LONG_RUN_PROGRESSIVE,
            name=f"{distance_km:.0f}km Progressive Long Run",
            description=(
                "Start easy, build to marathon pace, finish at"
                " threshold. Develops pacing and fatigue resistance."
            ),
            purpose=TrainingPurpose.MENTAL_TOUGHNESS,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def long_run_with_race_pace(self, distance_km: float, race_pace_km: float = 4) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        warmup_km = 3
        cooldown_km = 2
        easy_km = distance_km - warmup_km - cooldown_km - race_pace_km
        if easy_km < 0:
            easy_km = 1
        dur = None
        if p:
            dur = (warmup_km + cooldown_km + easy_km) * p.easy_low + race_pace_km * p.marathon
        mp_lo, mp_hi = self._resolve_pace("race")
        steps = [
            self._warmup(15),
            self._easy_step(distance_meters=easy_km * 1000),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{race_pace_km:.0f} km at race pace",
                distance_meters=race_pace_km * 1000,
                pace_low=mp_lo,
                pace_high=mp_hi,
                pace_key="race",
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.LONG_RUN_WITH_RACE_PACE,
            name=f"{distance_km:.0f}km Long Run w/ {race_pace_km:.0f}km Race Pace",
            description=(
                "Long run with a sustained race-pace block to"
                " build specificity and confidence."
            ),
            purpose=TrainingPurpose.RACE_SPECIFICITY,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def tempo(self, tempo_km: float) -> Workout:
        total_km = tempo_km + 3  # ~1.5km warmup + 1.5km cooldown
        dist_m = total_km * 1000
        p = self.paces
        dur = None
        if p:
            dur = 10 * 60 + tempo_km * p.threshold + 10 * 60  # warmup + tempo + cooldown
        t_lo, t_hi = self._resolve_pace("threshold")
        steps = [
            self._warmup(10),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{tempo_km:.0f} km tempo at threshold pace",
                distance_meters=tempo_km * 1000,
                pace_low=t_lo,
                pace_high=t_hi,
                pace_key="threshold",
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.TEMPO,
            name=f"{tempo_km:.0f}km Tempo Run",
            description=(
                "Sustained threshold-pace effort. Develops"
                " lactate clearance and mental focus."
            ),
            purpose=TrainingPurpose.LACTATE_THRESHOLD,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def threshold_cruise_intervals(self, reps: int = 4, rep_min: float = 6) -> Workout:
        p = self.paces
        work_sec = reps * rep_min * 60
        rest_sec = reps * 60  # 1 min recovery between reps
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        dur = warmup_sec + work_sec + rest_sec + cooldown_sec
        est_dist = None
        if p:
            est_dist = (
                (warmup_sec + cooldown_sec) / p.easy_low * 1000
                + work_sec / p.threshold * 1000
            )
        t_lo, t_hi = self._resolve_pace("threshold")
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x {rep_min:.0f} min cruise intervals",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        f"{rep_min:.0f} min at threshold",
                        duration_seconds=rep_min * 60,
                        pace_low=t_lo,
                        pace_high=t_hi,
                        pace_key="threshold",
                    ),
                    self._recovery_step(60),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.THRESHOLD,
            name=f"{reps} x {rep_min:.0f}min Cruise Intervals",
            description=(
                "Broken threshold work with short recoveries."
                " Same lactate benefit as tempo with less mental fatigue."
            ),
            purpose=TrainingPurpose.LACTATE_THRESHOLD,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def vo2max_intervals(self, reps: int = 5, rep_min: float = 3.5) -> Workout:
        p = self.paces
        work_sec = reps * rep_min * 60
        rest_sec = reps * rep_min * 60  # equal recovery
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        dur = warmup_sec + work_sec + rest_sec + cooldown_sec
        est_dist = None
        if p:
            est_dist = (
                (warmup_sec + cooldown_sec) / p.easy_low * 1000
                + work_sec / p.interval * 1000
            )
        i_lo, i_hi = self._resolve_pace("interval")
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x {rep_min:.1f} min VO2max intervals",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        f"{rep_min:.1f} min at I pace",
                        duration_seconds=rep_min * 60,
                        pace_low=i_lo,
                        pace_high=i_hi,
                        pace_key="interval",
                    ),
                    self._recovery_step(rep_min * 60),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.VO2MAX,
            name=f"{reps} x {rep_min:.1f}min VO2max Intervals",
            description=(
                "Hard intervals at VO2max intensity to raise"
                " aerobic ceiling. Full recovery between reps."
            ),
            purpose=TrainingPurpose.VO2MAX,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def speed_400s(self, reps: int = 8) -> Workout:
        p = self.paces
        rep_dist = 400
        rest_sec = 90  # 400m recovery jog
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        work_sec = reps * (rep_dist / 1000 * (p.repetition if p else 240))
        dur = warmup_sec + work_sec + reps * rest_sec + cooldown_sec
        est_dist = reps * rep_dist + 4000  # ~4km warm/cool
        r_lo, r_hi = self._resolve_pace("repetition")
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x 400m at R pace",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        "400m at R pace",
                        distance_meters=400,
                        pace_low=r_lo,
                        pace_high=r_hi,
                        pace_key="repetition",
                    ),
                    self._recovery_step(rest_sec),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.SPEED,
            name=f"{reps} x 400m Speed Reps",
            description="Short, fast repetitions developing speed and running economy at R pace.",
            purpose=TrainingPurpose.SPEED_NEUROMUSCULAR,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def speed_200s(self, reps: int = 10) -> Workout:
        p = self.paces
        rep_dist = 200
        rest_sec = 60
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        work_sec = reps * (rep_dist / 1000 * (p.repetition if p else 240))
        dur = warmup_sec + work_sec + reps * rest_sec + cooldown_sec
        est_dist = reps * rep_dist + 4000
        r_lo, r_hi = self._resolve_pace("repetition")
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x 200m at R pace",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        "200m at R pace",
                        distance_meters=200,
                        pace_low=r_lo,
                        pace_high=r_hi,
                        pace_key="repetition",
                    ),
                    self._recovery_step(rest_sec),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.SPEED,
            name=f"{reps} x 200m Speed Reps",
            description="Quick 200m repeats at R pace for neuromuscular speed and form.",
            purpose=TrainingPurpose.SPEED_NEUROMUSCULAR,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def hills(self, reps: int = 8, hill_sec: float = 60) -> Workout:
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        rest_sec = 90
        dur = warmup_sec + reps * (hill_sec + rest_sec) + cooldown_sec
        est_dist = 6000 + reps * 200  # rough estimate
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x {hill_sec:.0f}s hill reps",
                repeat_count=reps,
                steps=[
                    WorkoutStep(
                        step_type=WorkoutStepType.INTERVAL,
                        description=f"{hill_sec:.0f}s hard uphill effort",
                        duration_seconds=hill_sec,
                        target_type=IntensityTarget.OPEN,
                    ),
                    self._recovery_step(rest_sec),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.HILLS,
            name=f"{reps} x {hill_sec:.0f}s Hill Reps",
            description=(
                "Hill repetitions build strength, power, and"
                " running economy. Effort should be hard but controlled."
            ),
            purpose=TrainingPurpose.RUNNING_ECONOMY,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
            cadence_target=170,
        )

    def fartlek(self, total_min: float = 40) -> Workout:
        p = self.paces
        dur = total_min * 60
        est_dist = None
        if p:
            avg_pace = (p.easy_low + p.threshold) / 2
            est_dist = dur / avg_pace * 1000
        i_lo, i_hi = self._resolve_pace("interval")
        t_lo, t_hi = self._resolve_pace("threshold")
        steps = [
            self._warmup(10),
            # Alternating surges — modeled as a repeat block
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description="Fartlek surges — varied pace",
                repeat_count=6,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        "2 min hard surge",
                        duration_seconds=120,
                        pace_low=t_lo,
                        pace_high=i_hi,
                    ),
                    self._recovery_step(120),
                ],
            ),
            self._cooldown(6),
        ]
        return Workout(
            workout_type=WorkoutType.FARTLEK,
            name=f"{total_min:.0f}min Fartlek",
            description=(
                "Unstructured speed play — alternate between"
                " hard surges and easy running by feel."
            ),
            purpose=TrainingPurpose.AEROBIC_BASE,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def progressive_run(self, distance_km: float) -> Workout:
        dist_m = distance_km * 1000
        p = self.paces
        thirds = distance_km / 3
        dur = None
        if p:
            dur = thirds * p.easy_low + thirds * p.marathon + thirds * p.threshold
        mp_lo, mp_hi = self._resolve_pace("marathon")
        t_lo, t_hi = self._resolve_pace("threshold")
        steps = [
            self._easy_step(distance_meters=thirds * 1000),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{thirds:.1f} km at marathon pace",
                distance_meters=thirds * 1000,
                pace_low=mp_lo,
                pace_high=mp_hi,
                pace_key="marathon",
            ),
            self._pace_step(
                WorkoutStepType.ACTIVE,
                f"{thirds:.1f} km at threshold pace",
                distance_meters=thirds * 1000,
                pace_low=t_lo,
                pace_high=t_hi,
                pace_key="threshold",
            ),
        ]
        return Workout(
            workout_type=WorkoutType.PROGRESSIVE,
            name=f"{distance_km:.0f}km Progressive Run",
            description=(
                "Start easy, finish fast. Each third gets progressively"
                " faster developing pacing discipline."
            ),
            purpose=TrainingPurpose.LACTATE_THRESHOLD,
            estimated_distance_meters=dist_m,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    # ── HYROX generators ─────────────────────────────────────────────
    # Station names match paceforge.hyrox.models.STATION_SPLITS so weak-station
    # priorities from race analysis can drive session focus directly.

    _STATION_DISPLAY = {
        "SkiErg_1000m": "Ski Erg 1000m", "Sled_Push_50m": "Sled Push 50m",
        "Sled_Pull_50m": "Sled Pull 50m", "Burpee_Broad_Jump_80m": "Burpee Broad Jumps 80m",
        "Row_1000m": "Row 1000m", "Farmers_Carry_200m": "Farmers Carry 200m",
        "Sandbag_Lunges_100m": "Sandbag Lunges 100m", "Wall_Balls": "Wall Balls 75 reps",
    }

    def _station_name(self, station: str) -> str:
        return self._STATION_DISPLAY.get(station, station.replace("_", " "))

    def hyrox_compromised_brick(self, reps: int = 6, stations: list[str] | None = None,
                                station_min: float = 3.0, pace_key: str = "threshold") -> Workout:
        """Station effort + 1km run, repeated — running on tired legs is THE
        HYROX-specific skill (race runs happen compromised, never fresh)."""
        focus = stations or ["SkiErg_1000m", "Sled_Push_50m", "Row_1000m"]
        rotation = ", ".join(self._station_name(s) for s in focus)
        pace_lo, pace_hi = self._resolve_pace(pace_key)
        run_sec = 1000 / 1000 * (pace_lo if pace_lo else 300) * reps
        work_sec = reps * station_min * 60 + run_sec
        dur = 10 * 60 + work_sec + 10 * 60
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x (station effort + 1km compromised run)",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.ACTIVE,
                        f"{station_min:.0f} min hard station effort — rotate: {rotation}",
                        duration_seconds=station_min * 60,
                    ),
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        f"1 km at {pace_key} pace straight off the station",
                        distance_meters=1000,
                        pace_low=pace_lo,
                        pace_high=pace_hi,
                        pace_key=pace_key,
                    ),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.HYROX_MIXED,
            name=f"Compromised Brick — {reps}x(station + 1km)",
            description=(
                f"Alternate a {station_min:.0f}-min hard station effort ({rotation}) with a 1km "
                f"run at {pace_key} pace, no rest between. Trains race-specific running on "
                "loaded legs — hold the run pace even when the legs argue."
            ),
            purpose=TrainingPurpose.RACE_SPECIFICITY,
            estimated_distance_meters=reps * 1000 + 4000,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def hyrox_race_simulation(self, segments: int = 4, stations: list[str] | None = None,
                              pace_key: str = "threshold") -> Workout:
        """Partial race rehearsal: N x (1km at race pace + full station), racing the
        transitions too (roxzone is 'free time' — average athletes give away ~4 min)."""
        order = stations or ["SkiErg_1000m", "Sled_Push_50m", "Burpee_Broad_Jump_80m", "Row_1000m"]
        order = (order * ((segments // len(order)) + 1))[:segments]
        pace_lo, pace_hi = self._resolve_pace(pace_key)
        run_sec = segments * (pace_lo if pace_lo else 300)
        dur = 10 * 60 + run_sec + segments * 4 * 60 + 10 * 60
        steps: list[WorkoutStep] = [self._warmup(10)]
        for i, station in enumerate(order, 1):
            steps.append(self._pace_step(
                WorkoutStepType.INTERVAL,
                f"Run {i}: 1 km at race pace",
                distance_meters=1000,
                pace_low=pace_lo,
                pace_high=pace_hi,
                pace_key=pace_key,
            ))
            steps.append(self._pace_step(
                WorkoutStepType.ACTIVE,
                f"Station {i}: {self._station_name(station)} at race effort — fast transition in/out",
                duration_seconds=4 * 60,
            ))
        steps.append(self._cooldown(10))
        return Workout(
            workout_type=WorkoutType.HYROX_MIXED,
            name=f"HYROX Simulation — {segments}x(1km + station)",
            description=(
                f"{segments} race segments at target pace with full stations: "
                + " → ".join(self._station_name(s) for s in order)
                + ". Practice the transitions like race day — walk nothing."
            ),
            purpose=TrainingPurpose.RACE_SPECIFICITY,
            estimated_distance_meters=segments * 1000 + 4000,
            estimated_duration_seconds=dur,
            steps=steps,
        )

    def station_day(self, focus_stations: list[str] | None = None, sets: int = 4,
                    work_sec: float = 90, rest_sec: float = 90) -> Workout:
        """Structured station strength day (replaces the free-text notes day).
        Focus defaults come from race analysis priorities — weakest stations first."""
        focus = focus_stations or ["Sled_Push_50m", "Sled_Pull_50m", "Wall_Balls"]
        names = [self._station_name(s) for s in focus]
        steps: list[WorkoutStep] = [
            self._pace_step(WorkoutStepType.WARMUP,
                            "10 min general warmup + movement prep",
                            duration_seconds=10 * 60),
        ]
        for name in names:
            steps.append(WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{sets} x {name} — {work_sec:.0f}s hard / {rest_sec:.0f}s rest",
                repeat_count=sets,
                steps=[
                    self._pace_step(WorkoutStepType.ACTIVE,
                                    f"{name} at race effort",
                                    duration_seconds=work_sec),
                    self._pace_step(WorkoutStepType.REST,
                                    "Rest — full reset",
                                    duration_seconds=rest_sec),
                ],
            ))
        steps.append(self._cooldown(5))
        total = 10 * 60 + len(names) * sets * (work_sec + rest_sec) + 5 * 60
        return Workout(
            workout_type=WorkoutType.CROSS_TRAINING,
            name=f"Station Strength — {' / '.join(names)}",
            description=(
                f"{sets} rounds each of {', '.join(names)} at race effort "
                f"({work_sec:.0f}s on / {rest_sec:.0f}s off). Weakest stations first, "
                "while fresh — quality beats volume here."
            ),
            purpose=TrainingPurpose.RACE_SPECIFICITY,
            estimated_duration_seconds=total,
            steps=steps,
        )

    def race_pace_intervals(self, reps: int, rep_km: float, pace_key: str) -> Workout:
        warmup_sec = 10 * 60
        cooldown_sec = 10 * 60
        rest_sec = 90
        pace_lo, pace_hi = self._resolve_pace(pace_key)
        work_sec = reps * rep_km * (pace_lo if pace_lo else 300)
        dur = warmup_sec + work_sec + reps * rest_sec + cooldown_sec
        est_dist = reps * rep_km * 1000 + 4000
        steps = [
            self._warmup(10),
            WorkoutStep(
                step_type=WorkoutStepType.INTERVAL,
                description=f"{reps} x {rep_km:.1f}km at {pace_key} pace",
                repeat_count=reps,
                steps=[
                    self._pace_step(
                        WorkoutStepType.INTERVAL,
                        f"{rep_km:.1f} km at {pace_key} pace",
                        distance_meters=rep_km * 1000,
                        pace_low=pace_lo,
                        pace_high=pace_hi,
                        pace_key=pace_key,
                    ),
                    self._recovery_step(rest_sec),
                ],
            ),
            self._cooldown(10),
        ]
        return Workout(
            workout_type=WorkoutType.RACE_PACE,
            name=f"{reps} x {rep_km:.1f}km Race Pace Intervals",
            description=(
                f"Race-specific intervals at {pace_key} pace."
                " Builds confidence and specificity."
            ),
            purpose=TrainingPurpose.RACE_SPECIFICITY,
            estimated_distance_meters=est_dist,
            estimated_duration_seconds=dur,
            steps=steps,
        )
