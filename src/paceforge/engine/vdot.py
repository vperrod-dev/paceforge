"""VDOT pace calculator based on Jack Daniels' running formula.

Reference: Daniels' Running Formula (4th edition).
VDOT is an oxygen-consumption metric derived from race performance.
Given a VDOT value, we derive five training pace zones (sec/km).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── VDOT lookup table ────────────────────────────────────────────────
# Each entry: (vdot, easy_low, easy_high, marathon, threshold, interval, repetition)
# Paces in seconds per kilometre.

_VDOT_TABLE: list[tuple[int, float, float, float, float, float, float]] = [
    # VDOT  E-low   E-high   M       T       I       R
    (30, 434, 465, 414, 388, 360, 338),
    (31, 424, 453, 404, 378, 351, 329),
    (32, 414, 443, 395, 370, 343, 321),
    (33, 404, 434, 386, 361, 335, 314),
    (34, 395, 424, 377, 353, 327, 307),
    (35, 386, 416, 369, 345, 320, 300),
    (36, 378, 407, 361, 338, 313, 294),
    (37, 370, 399, 353, 331, 307, 288),
    (38, 362, 391, 346, 324, 300, 282),
    (39, 355, 384, 339, 317, 294, 276),
    (40, 348, 376, 332, 311, 288, 271),
    (41, 341, 370, 326, 305, 283, 266),
    (42, 334, 363, 319, 299, 278, 261),
    (43, 328, 357, 314, 294, 273, 256),
    (44, 322, 351, 308, 289, 268, 252),
    (45, 316, 345, 302, 284, 263, 247),
    (46, 311, 339, 297, 279, 259, 243),
    (47, 305, 334, 292, 274, 254, 239),
    (48, 300, 328, 287, 270, 250, 235),
    (49, 295, 323, 283, 266, 246, 231),
    (50, 290, 319, 278, 261, 243, 228),
    (51, 285, 314, 274, 257, 239, 224),
    (52, 281, 309, 270, 253, 235, 221),
    (53, 277, 305, 266, 250, 232, 218),
    (54, 273, 301, 262, 246, 228, 215),
    (55, 269, 297, 258, 243, 225, 212),
    (56, 265, 293, 255, 239, 222, 209),
    (57, 261, 289, 251, 236, 219, 206),
    (58, 257, 285, 248, 233, 216, 203),
    (59, 254, 282, 245, 230, 214, 201),
    (60, 250, 278, 241, 227, 211, 198),
    (61, 247, 275, 238, 224, 208, 196),
    (62, 244, 272, 235, 221, 206, 193),
    (63, 241, 268, 232, 219, 203, 191),
    (64, 238, 265, 230, 216, 201, 189),
    (65, 235, 262, 227, 214, 198, 187),
    (66, 232, 259, 224, 211, 196, 185),
    (67, 229, 257, 222, 209, 194, 183),
    (68, 226, 254, 219, 207, 192, 181),
    (69, 224, 251, 217, 205, 190, 179),
    (70, 221, 249, 215, 202, 188, 177),
    (71, 219, 246, 212, 200, 186, 175),
    (72, 216, 244, 210, 198, 184, 174),
    (73, 214, 242, 208, 196, 183, 172),
    (74, 212, 239, 206, 194, 181, 170),
    (75, 209, 237, 204, 193, 179, 169),
    (76, 207, 235, 202, 191, 177, 167),
    (77, 205, 233, 200, 189, 176, 166),
    (78, 203, 231, 198, 188, 174, 164),
    (79, 201, 229, 197, 186, 173, 163),
    (80, 199, 227, 195, 184, 171, 161),
    (85, 190, 218, 186, 176, 164, 155),
]


@dataclass(frozen=True)
class TrainingPaces:
    """Training paces in seconds per kilometre."""

    vdot: float
    easy_low: float
    easy_high: float
    marathon: float
    threshold: float
    interval: float
    repetition: float

    def easy_display(self) -> str:
        return f"{_fmt(self.easy_low)} - {_fmt(self.easy_high)}"

    def marathon_display(self) -> str:
        return _fmt(self.marathon)

    def threshold_display(self) -> str:
        return _fmt(self.threshold)

    def interval_display(self) -> str:
        return _fmt(self.interval)

    def repetition_display(self) -> str:
        return _fmt(self.repetition)

    def summary(self) -> dict[str, str]:
        return {
            "VDOT": str(round(self.vdot, 1)),
            "Easy": self.easy_display(),
            "Marathon": self.marathon_display(),
            "Threshold": self.threshold_display(),
            "Interval": self.interval_display(),
            "Repetition": self.repetition_display(),
        }


def _fmt(sec_per_km: float) -> str:
    """Format sec/km as M:SS/km."""
    m = int(sec_per_km) // 60
    s = int(sec_per_km) % 60
    return f"{m}:{s:02d}/km"


def _interpolate(vdot: float) -> TrainingPaces:
    """Linearly interpolate the VDOT table."""
    if vdot <= _VDOT_TABLE[0][0]:
        row = _VDOT_TABLE[0]
        return TrainingPaces(vdot, row[1], row[2], row[3], row[4], row[5], row[6])
    if vdot >= _VDOT_TABLE[-1][0]:
        row = _VDOT_TABLE[-1]
        return TrainingPaces(vdot, row[1], row[2], row[3], row[4], row[5], row[6])

    for i in range(len(_VDOT_TABLE) - 1):
        lo = _VDOT_TABLE[i]
        hi = _VDOT_TABLE[i + 1]
        if lo[0] <= vdot <= hi[0]:
            frac = (vdot - lo[0]) / (hi[0] - lo[0])
            return TrainingPaces(
                vdot=vdot,
                easy_low=lo[1] + frac * (hi[1] - lo[1]),
                easy_high=lo[2] + frac * (hi[2] - lo[2]),
                marathon=lo[3] + frac * (hi[3] - lo[3]),
                threshold=lo[4] + frac * (hi[4] - lo[4]),
                interval=lo[5] + frac * (hi[5] - lo[5]),
                repetition=lo[6] + frac * (hi[6] - lo[6]),
            )

    # Should not reach here
    row = _VDOT_TABLE[-1]
    return TrainingPaces(vdot, row[1], row[2], row[3], row[4], row[5], row[6])


def vdot_from_race(distance_meters: float, time_seconds: float) -> float:
    """Estimate VDOT from a race result using the Daniels & Gilbert formula.

    The formula relates VO2 to velocity and duration:
      VO2 = -4.60 + 0.182258 * v + 0.000104 * v^2
      %VO2max = 0.8 + 0.1894393 * e^(-0.012778*t) + 0.2989558 * e^(-0.1932605*t)
    where v = meters/min, t = minutes.
    """
    v = distance_meters / (time_seconds / 60.0)  # meters per minute
    t = time_seconds / 60.0  # minutes

    # VO2 at race pace
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v

    # Fraction of VO2max sustained
    pct = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)

    return vo2 / pct


def paces_from_vdot(vdot: float) -> TrainingPaces:
    """Get training paces for a given VDOT value."""
    return _interpolate(vdot)


def paces_from_race(distance_meters: float, time_seconds: float) -> TrainingPaces:
    """Calculate training paces from a race result."""
    vdot = vdot_from_race(distance_meters, time_seconds)
    return paces_from_vdot(vdot)


# ── Convenience: common race distances in meters ─────────────────────

RACE_DISTANCES = {
    "5K": 5000,
    "10K": 10000,
    "HALF_MARATHON": 21097.5,
    "MARATHON": 42195,
}


def normalize_lt_speed(raw_speed: float | None) -> float | None:
    """Normalize Garmin LT speed to m/s.

    Garmin sometimes returns LT speed in unexpected units. Valid running
    LT speed is roughly 2.5-6.5 m/s (6:40/km to 2:34/km). If the value is
    outside that range, try common unit conversions; return None when no
    interpretation is credible.
    """
    if not raw_speed or raw_speed <= 0:
        return None
    if 2.0 <= raw_speed <= 7.0:  # already m/s
        return raw_speed
    if 200 <= raw_speed <= 700:  # cm/s
        return raw_speed / 100
    if raw_speed >= 2000:  # mm/s (incl. m/s*1000 stored as int)
        return raw_speed / 1000
    if raw_speed < 2.0 and 2.0 <= raw_speed * 10 <= 7.0:  # tenths bug
        return raw_speed * 10
    return None  # Unreliable — don't use
