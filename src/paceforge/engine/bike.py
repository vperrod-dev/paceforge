"""Cycling power maths — Coggan zones, NP/IF/TSS, ramp-test FTP, progression levels."""

from __future__ import annotations

# Coggan 7-zone model as (low, high) fractions of FTP; None = unbounded top.
COGGAN_ZONES: dict[str, tuple[float, float | None]] = {
    "Z1 Active Recovery": (0.0, 0.55),
    "Z2 Endurance": (0.55, 0.75),
    "Z3 Tempo": (0.75, 0.90),
    "Z4 Threshold": (0.90, 1.05),
    "Z5 VO2max": (1.05, 1.20),
    "Z6 Anaerobic": (1.20, 1.50),
    "Z7 Neuromuscular": (1.50, None),
}


def power_zones(ftp: int) -> dict[str, tuple[int, int | None]]:
    """Watt ranges for the Coggan zones at a given FTP."""
    return {
        name: (round(ftp * low), round(ftp * high) if high is not None else None)
        for name, (low, high) in COGGAN_ZONES.items()
    }


def normalized_power(samples: list[float], hz: float = 1.0) -> float:
    """NP: 30s rolling average, 4th power, mean, 4th root (plain average under 30s)."""
    if not samples:
        return 0.0
    window = max(int(30 * hz), 1)
    if len(samples) < window:
        return sum(samples) / len(samples)
    rolling = []
    total = sum(samples[:window])
    rolling.append(total / window)
    for i in range(window, len(samples)):
        total += samples[i] - samples[i - window]
        rolling.append(total / window)
    return (sum(r**4 for r in rolling) / len(rolling)) ** 0.25


def intensity_factor(np: float, ftp: float) -> float:
    """IF = NP / FTP."""
    return np / ftp


def tss(duration_sec: float, np: float, ftp: float) -> float:
    """TSS = duration * NP * IF / (FTP * 3600) * 100."""
    return duration_sec * np * intensity_factor(np, ftp) / (ftp * 3600) * 100


def ramp_test_ftp(best_1min_power: float) -> int:
    """FTP estimate from a ramp test: 75% of the best 1-minute power."""
    return round(0.75 * best_1min_power)


def estimate_workout_tss(steps: list[tuple[float, float]], ftp: float) -> float:
    """Planned TSS for a [(duration_sec, target_watts)] step timeline."""
    # ponytail: expand to 1Hz samples and reuse normalized_power — a 3h ride is ~11k floats.
    samples = [watts for dur, watts in steps for _ in range(int(dur))]
    if not samples:
        return 0.0
    return tss(len(samples), normalized_power(samples), ftp)


def progression_update(level: float, outcome: str) -> float:
    """Adjust a 1-10 progression level: pass +0.4, struggled +0.1, failed -0.5, clamped."""
    delta = {"pass": 0.4, "struggled": 0.1, "failed": -0.5}.get(outcome, 0.0)
    return round(min(max(level + delta, 1.0), 10.0), 1)


def suggest_next_level(level: float) -> float:
    """Target level for the next workout of the same type."""
    return round(min(level + 0.3, 10.0), 1)
